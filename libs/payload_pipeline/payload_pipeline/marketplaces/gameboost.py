"""Reusable GameBoost base builder.

Extracts the boilerplate repeated across all 12 game-specific GameBoost
builders: slug generation, credential formatting, delivery instructions,
pricing, and the static payload skeleton.  Game slices subclass and
implement only ``_game_slug``, ``_build_account_data``, and optionally
``_build_dump`` / ``_build_game_items``.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any

from ..core.contracts import BuildContext, ListingDraft
from ..core.enums import ListingKind
from .base import BasePayloadBuilder, _DISCLAIMER, _DROPSHIPPING_DELIVERY


def _extract_mail_provider(email_login_link: str | None) -> str | None:
    """Extract mail provider domain from email_login_link.

    Examples:
        'firstmail.ltd/webmail'       → 'firstmail.ltd'
        'https://outlook.com/mail'    → 'outlook.com'
        ''  / None                    → None
    """
    if not email_login_link:
        return None
    link = re.sub(r"^https?://", "", email_login_link.strip())
    domain = link.split("/")[0].strip()
    return domain or None


class BaseGameBoostBuilder(BasePayloadBuilder[Any]):
    """Common shape for GameBoost account payloads.

    Subclasses **must** implement:
    * ``game_slug`` — the GameBoost game identifier (e.g. ``"valorant"``).
    * ``_build_account_data`` — game-specific account_data dict.

    Subclasses **may** override:
    * ``_build_dump`` — returns tag string, default ``None`` (omitted).
    * ``_build_game_items`` — returns game_items dict, default ``None`` (omitted).
    * ``_format_delivery`` — credential formatting, default uses standard template.
    * ``_platform_name`` — label used in delivery instructions (e.g. ``"Riot Account"``).
    """

    marketplace = "gameboost"

    @property
    @abstractmethod
    def game_slug(self) -> str:
        """GameBoost game identifier (e.g. ``"valorant"``, ``"counter-strike-2"``)."""

    @abstractmethod
    def _build_account_data(self, subject: Any) -> dict[str, Any]:
        """Return the game-specific ``account_data`` dict."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        content = listing.content_for(self.marketplace)
        price = self._apply_pricing(subject.price, ctx)
        if ctx.exchange_rate is not None:
            price = round(price * ctx.exchange_rate, 2)
        is_stock = ctx.kind == ListingKind.STOCK
        creds = subject.credentials

        payload: dict[str, Any] = {
            "game": self.game_slug,
            "title": content.title,
            "slug": self._generate_slug(content.title),
            "price": price,
            "ign": "",
            "login": creds.login if is_stock else None,
            "password": creds.password if is_stock else None,
            "email_login": (creds.email_login or "cometochat") if is_stock else None,
            "email_password": (
                creds.email_password
                if is_stock and creds.email_login
                else ("cometochat" if is_stock else None)
            ),
            "mail_provider": _extract_mail_provider(creds.email_login_link) if is_stock else None,
            "is_manual": not is_stock,
            "delivery_time": {} if is_stock else {"duration": 10, "unit": "minutes"},
            "has_2fa": False,
            "level_up_method": "by_hand",
            "description": content.description,
            "delivery_instructions": (
                _DISCLAIMER if is_stock
                else _DROPSHIPPING_DELIVERY
            ),
            "image_urls": list(listing.media.external_urls) if listing.media.external_urls else [],
            "account_data": self._build_account_data(subject),
        }

        dump = self._build_dump(subject)
        if dump is not None:
            payload["dump"] = dump

        game_items = self._build_game_items(subject)
        if game_items is not None:
            payload["game_items"] = game_items

        return payload

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    @property
    def _platform_name(self) -> str:
        """Label for credential lines (e.g. ``"Steam Account"``)."""
        return "Account"

    def _build_dump(self, subject: Any) -> str | None:
        """Return tag string or ``None`` to omit from payload."""
        return None

    def _build_game_items(self, subject: Any) -> dict[str, Any] | None:
        """Return game_items dict or ``None`` to omit from payload."""
        return None

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_slug(title: str) -> str:
        text = re.sub(r"[^\w\s-]", "", title)
        return re.sub(r"\s+", "-", text.strip()).lower()
