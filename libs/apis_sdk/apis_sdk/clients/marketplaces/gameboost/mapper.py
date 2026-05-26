"""
GameBoost mapper.

Extracts structured data from GameBoost API responses and builds
create-offer payloads from raw sync data.

Output-side:
- Pagination metadata
- Request ID
- Rate-limit headers
- Response data extraction

Input-side (relist support):
- build_from_raw: converts sync raw_data → create_offer payload
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from apis_sdk.clients.marketplaces.gameboost.models import GameBoostPaginationMeta


class GameBoostMapper:
    """
    Mapper for GameBoost API responses and request payloads.

    Output-side: extracts metadata from response headers and body.
    Input-side: builds create_offer payloads from raw sync data.
    """

    @staticmethod
    def extract_request_id(
        headers: Mapping[str, str],
        body: Any = None,
    ) -> str | None:
        """
        Extract request ID from response headers or body.

        GameBoost uses several header variants for request tracking.
        """
        for key in (
            "X-GameBoost-Request-Id",
            "X-Request-Id",
            "x-gameboost-request-id",
            "x-request-id",
        ):
            value = headers.get(key)
            if value:
                return value
        if isinstance(body, dict):
            rid = body.get("request_id") or body.get("requestId")
            if isinstance(rid, str):
                return rid
        return None

    @staticmethod
    def extract_rate_limit_meta(headers: Mapping[str, str]) -> dict[str, str]:
        """
        Extract rate-limit headers from response.

        Returns raw header values for downstream consumers.
        """
        meta: dict[str, str] = {}
        for key in (
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
        ):
            value = headers.get(key)
            if value:
                meta[key] = value
        return meta

    @staticmethod
    def extract_pagination_meta(body: Any) -> GameBoostPaginationMeta | None:
        """
        Extract pagination metadata from a list response body.

        GameBoost wraps pagination info in a top-level ``meta`` key.
        Returns None if no pagination metadata is present.
        """
        if not isinstance(body, dict):
            return None
        meta_block = body.get("meta")
        if not isinstance(meta_block, dict):
            return None
        return GameBoostPaginationMeta.model_validate(meta_block)

    @staticmethod
    def extract_list_data(body: Any) -> list[Any]:
        """
        Extract the data array from a paginated list response.

        GameBoost wraps list data in a ``data`` key. Falls back to
        the body itself if it's already a list.
        """
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, list):
                return data
        return []

    # ------------------------------------------------------------------
    # Input-side: build create-offer payload from raw sync data
    # ------------------------------------------------------------------

    @staticmethod
    def build_from_raw(raw_data: dict[str, Any]) -> dict[str, Any]:
        """Build a create_offer payload from raw GameBoost sync data.

        Takes the structure stored in Listing.raw_data (sync format with
        nested game object, price objects, and credential entries) and
        converts it to the flat structure expected by the create_offer API.

        Args:
            raw_data: Raw offer dict from GB sync (includes ``game``,
                ``price_usd``, ``_credential_entries``, etc.).

        Returns:
            Ready-to-send payload dict for ``create_offer()`` or
            ``create_offer_with_credentials()``.
        """
        # --- game -------------------------------------------------------------
        game_obj = raw_data.get('game') or {}
        game_slug = game_obj.get('slug') or raw_data.get('game_slug') or ''

        # --- pricing ----------------------------------------------------------
        price_obj = raw_data.get('price') or {}
        price = float(price_obj.get('value', 0)) if price_obj else 0.0
        if not price:
            price_usd_obj = raw_data.get('price_usd') or {}
            price = float(price_usd_obj.get('value', 0)) if price_usd_obj else 0.0

        # --- title / description ----------------------------------------------
        title = raw_data.get('title') or ''
        slug = raw_data.get('slug') or _generate_slug(title)
        description = raw_data.get('description') or ''

        # --- delivery ---------------------------------------------------------
        is_manual = raw_data.get('is_manual_delivery', False)
        delivery_instructions = raw_data.get('delivery_instructions') or ''
        delivery_time = _extract_delivery_time(raw_data, is_manual)

        # --- credentials ------------------------------------------------------
        credentials_list = _extract_credentials(raw_data)

        # --- images -----------------------------------------------------------
        image_urls = raw_data.get('image_urls') or []

        # --- account_data (parameters in sync format) -------------------------
        account_data = _extract_account_data(raw_data)

        # --- dump (tag string for SEO) ----------------------------------------
        dump = raw_data.get('dump') or ''

        # Build payload for multi-credential endpoint
        payload: dict[str, Any] = {
            'game': game_slug,
            'title': title,
            'slug': slug,
            'price': round(price, 2),
            'ign': '',
            'is_manual': is_manual,
            'delivery_time': delivery_time,
            'has_2fa': False,
            'level_up_method': 'by_hand',
            'description': description,
            'delivery_instructions': delivery_instructions,
            'image_urls': image_urls,
            'account_data': account_data,
        }

        if dump:
            payload['dump'] = dump

        # Use multi-credential format if we have credential entries
        if credentials_list:
            payload['credentials'] = credentials_list
        else:
            # Fallback to legacy single-credential format
            inline_creds = raw_data.get('credentials') or {}
            payload['login'] = inline_creds.get('login') or ''
            payload['password'] = inline_creds.get('password') or ''
            payload['email_login'] = inline_creds.get('email_login') or None
            payload['email_password'] = inline_creds.get('email_password') or None
            payload['mail_provider'] = inline_creds.get('email_provider') or None

        return payload


def _extract_credentials(raw_data: dict[str, Any]) -> list[str]:
    """Extract credential strings from raw_data for multi-credential endpoint.

    Sources (in priority order):
    1. ``_credential_entries`` — API-populated list of credential dicts
    2. ``credentials`` inline dict — legacy single-credential format
    """
    entries = raw_data.get('_credential_entries') or []
    if entries:
        result: list[str] = []
        for entry in entries:
            cred_text = entry.get('credentials') or ''
            if cred_text and not entry.get('is_sold', False):
                result.append(cred_text)
        return result

    # Fallback: build from inline credentials dict
    inline = raw_data.get('credentials') or {}
    login = inline.get('login')
    password = inline.get('password')
    if login and password:
        parts = [f"Login: {login}", f"Password: {password}"]
        email_login = inline.get('email_login')
        email_password = inline.get('email_password')
        if email_login:
            parts.append(f"Email: {email_login}")
        if email_password:
            parts.append(f"Email Password: {email_password}")
        return ['\n'.join(parts)]

    return []


def _extract_account_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Extract account_data from raw sync data.

    Sync raw_data stores game parameters under ``parameters``.
    This is exactly what the GB create API expects as ``account_data``.
    """
    params = raw_data.get('parameters') or {}
    if params:
        return dict(params)

    # Dropship format might already have account_data
    return raw_data.get('account_data') or {}


def _extract_delivery_time(raw_data: dict[str, Any], is_manual: bool) -> dict[str, Any]:
    """Extract delivery_time from raw sync data.

    Sync raw_data has a rich ``delivery_time`` object from the GB API.
    We only need ``duration`` and ``unit`` for the create payload.
    Falls back to sensible defaults based on is_manual.
    """
    dt = raw_data.get('delivery_time') or {}
    if dt:
        duration = dt.get('duration', 0)
        unit = dt.get('unit', 'seconds')
        # GB API uses seconds=0 for instant — map to empty dict
        if unit == 'seconds' and duration == 0:
            return {}
        # Normalise to the units the create API accepts
        if unit == 'seconds' and duration > 0:
            return {'duration': max(1, duration // 60), 'unit': 'minutes'}
        if unit in ('minutes', 'hours', 'days'):
            return {'duration': duration, 'unit': unit}

    # Default: instant for stock, 10 min for manual
    return {} if not is_manual else {'duration': 10, 'unit': 'minutes'}


def _generate_slug(title: str) -> str:
    """Generate URL-safe slug from title."""
    text = re.sub(r"[^\w\s-]", "", title)
    return re.sub(r"\s+", "-", text.strip()).lower()
