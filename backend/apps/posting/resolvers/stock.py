"""Stock resolver — OwnedProduct lookup + LZT fallback + raw_data validation."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from django.utils import timezone

from apps.inventory.models import OwnedProduct, Game
from apps.sync.enums import ParseStatus, ResourceType
from apps.sync.models import RawPayload
from apps.sync.services.lzt import mapper
from apps.sync.services.lzt.service import LztOwnedProductSyncService

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


class DataMissing(Exception):
    """OwnedProduct not found or raw_data empty."""

    def __init__(self, login: str, reason: str = ''):
        self.login = login
        self.reason = reason
        super().__init__(f"Data missing for '{login}': {reason}")


@dataclass
class ResolverResult:
    """Successful resolve output."""
    owned_product: OwnedProduct
    sources: dict[str, Any]


class StockResolver:
    """Looks up OwnedProduct by login + game category, validates raw_data.

    If lzt_facade and lzt_account are provided, falls back to LZT API
    when OwnedProduct is missing or has empty raw_data.
    """

    def __init__(
        self,
        lzt_facade=None,
        lzt_account: IntegrationAccount | None = None,
    ):
        self._lzt_facade = lzt_facade
        self._lzt_account = lzt_account

    def resolve(self, login: str, game: Game) -> ResolverResult:
        """Resolve a login to an OwnedProduct with raw_data.

        Raises:
            DataMissing: if product not found, game has no category, or raw_data empty.
        """
        if not game.category_id:
            raise DataMissing(login, 'Game has no category assigned')

        normalized = login.lower().strip()

        owned = (
            OwnedProduct.objects
            .filter(category=game.category, login=normalized)
            .select_related('source_account')
            .first()
        )

        _source_provider = (
            owned.source_account.provider
            if owned and owned.source_account
            else None
        )
        needs_fallback = (
            owned is None
            or not owned.raw_data
            or (_source_provider is not None and _source_provider != 'lzt')
        )

        if needs_fallback and self._lzt_facade and self._lzt_account:
            owned = self._lzt_fallback(normalized, game, existing=owned)

        if owned is None:
            raise DataMissing(login, 'OwnedProduct not found')

        if not owned.raw_data:
            raise DataMissing(login, 'raw_data is empty')

        # Build sources dict keyed by provider name
        provider = 'lzt'  # default source
        if owned.source_account and owned.source_account.provider:
            provider = owned.source_account.provider
        sources = {provider: owned.raw_data}

        return ResolverResult(owned_product=owned, sources=sources)

    # ------------------------------------------------------------------
    # LZT fallback
    # ------------------------------------------------------------------

    def _lzt_fallback(
        self,
        login: str,
        game: Game,
        existing: OwnedProduct | None,
    ) -> OwnedProduct | None:
        """Try to fetch item from LZT API and create/update OwnedProduct.

        Flow:
        1. get_user_orders(login=...) — purchased account
        2. RawPayload upsert (change detection via payload_hash)
        3. parse_and_apply → OwnedProduct created/updated
        """
        item = self._fetch_from_lzt(login)
        if not item:
            logger.info("LZT fallback: '%s' not found in LZT", login)
            return existing  # return whatever we had (None or empty raw_data)

        # Category mismatch check — catch wrong game selection early.
        # Compare by numeric category_id (LZT external ID) stored on our
        # Category model, not by name which may differ between systems.
        lzt_cat_id = (item.get('category') or {}).get('category_id')
        our_cat_id = game.category.category_id if game.category else None
        if lzt_cat_id is not None and our_cat_id is not None and int(lzt_cat_id) != int(our_cat_id):
            lzt_cat_name = (item.get('category') or {}).get('category_name', '?')
            raise DataMissing(
                login,
                f"Category mismatch: account is '{lzt_cat_name}' (id={lzt_cat_id})"
                f" but job game is '{game.name}' (category_id={our_cat_id})",
            )

        # Upsert RawPayload
        remote_id = mapper.extract_remote_id(item)
        if not remote_id:
            logger.warning("LZT fallback: '%s' — no item_id in response", login)
            return existing

        raw_payload = self._upsert_raw_payload(remote_id, item)

        # Parse via existing service logic
        if raw_payload.parse_status == ParseStatus.PENDING:
            try:
                svc = LztOwnedProductSyncService()
                svc.parse_and_apply(raw_payload)
                raw_payload.parse_status = ParseStatus.PARSED
                raw_payload.parsed_at = timezone.now()
                raw_payload.save(update_fields=[
                    'parse_status', 'parsed_at', 'updated_at',
                ])
                logger.info(
                    "LZT fallback: imported '%s' (item_id=%s)", login, remote_id,
                )
            except Exception as exc:
                raw_payload.parse_status = ParseStatus.FAILED
                raw_payload.parse_error = str(exc)
                raw_payload.save(update_fields=[
                    'parse_status', 'parse_error', 'updated_at',
                ])
                logger.warning(
                    "LZT fallback: parse failed for '%s': %s", login, exc,
                )
                return existing

        # Re-fetch OwnedProduct (now should exist with raw_data)
        owned = (
            OwnedProduct.objects
            .filter(category=game.category, login=login)
            .select_related('source_account')
            .first()
        )
        return owned

    def _fetch_from_lzt(self, login: str) -> dict | None:
        """Fetch item from LZT by login.

        Tries two sources in order:
        1. /user/orders (purchased accounts) — login filter
        2. /user/items?show=closed (own closed listings) — login filter
        """
        # 1) Purchased accounts
        item = self._search_lzt_endpoint(
            self._lzt_facade.get_user_orders, login,
        )
        if item:
            return item

        # 2) Own closed listings
        item = self._search_lzt_endpoint(
            self._lzt_facade.get_user_items, login,
            extra_params={'show': 'closed'},
        )
        return item

    def _search_lzt_endpoint(
        self,
        api_method,
        login: str,
        extra_params: dict | None = None,
    ) -> dict | None:
        """Call an LZT list endpoint with login filter, return exact match."""
        params = {'login': login}
        if extra_params:
            params.update(extra_params)

        result = api_method(params=params)
        if not result.ok or not result.data:
            return None

        items = result.data.items if result.data else []
        if not items:
            return None

        for item in items:
            if mapper.has_login_data(item):
                try:
                    item_login, _ = mapper.extract_login_data(item)
                    if item_login.lower().strip() == login:
                        return item
                except ValueError:
                    continue

        logger.info("LZT fallback: no exact login match for '%s' (%d items checked)", login, len(items))
        return None

    def _upsert_raw_payload(self, remote_id: str, item: dict) -> RawPayload:
        """Upsert RawPayload — same logic as BaseSyncService._ingest_raw."""
        now = timezone.now()
        payload_hash = hashlib.sha256(
            json.dumps(item, sort_keys=True, default=str).encode()
        ).hexdigest()

        raw, created = RawPayload.objects.get_or_create(
            integration_account=self._lzt_account,
            resource_type=ResourceType.OWNED_PRODUCTS,
            remote_id=remote_id,
            defaults={
                'payload': item,
                'payload_hash': payload_hash,
                'first_seen_at': now,
                'last_seen_at': now,
                'fetched_at': now,
                'parse_status': ParseStatus.PENDING,
            },
        )

        if not created:
            raw.last_seen_at = now
            raw.fetched_at = now
            if raw.payload_hash != payload_hash:
                raw.payload = item
                raw.payload_hash = payload_hash
                raw.parse_status = ParseStatus.PENDING
                raw.parse_error = ''
                raw.parsed_at = None
                raw.save(update_fields=[
                    'payload', 'payload_hash', 'parse_status',
                    'parse_error', 'parsed_at',
                    'last_seen_at', 'fetched_at', 'updated_at',
                ])
            else:
                raw.save(update_fields=[
                    'last_seen_at', 'fetched_at', 'updated_at',
                ])

        return raw
