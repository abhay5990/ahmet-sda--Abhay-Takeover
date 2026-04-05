from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.inventory.enums import OwnedProductStatus
from apps.inventory.models import Category
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from apps.sync.services.shared.owned_product import get_or_create_owned_product
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


class LztOwnedProductSyncService(BaseSyncService):
    """Sync LZT purchased items into OwnedProduct.

    Three modes of operation:
    - File import: management command feeds items from JSON via _ingest_raw.
    - API import:  management command fetches all pages from LZT API.
    - Incremental: fetch_page calls LZT API for new purchases since
      last checkpoint (used by scheduler).

    Usage: python manage.py import_lzt_orders <account> --source file|api
    """

    resource_type = ResourceType.OWNED_PRODUCTS

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client
        self._category_cache: dict[int, Category] = {}

    def _get_category(self, lzt_category_id: int) -> Category:
        """Cached category lookup — single DB hit per category_id."""
        if lzt_category_id not in self._category_cache:
            self._category_cache[lzt_category_id] = Category.objects.get(
                category_id=lzt_category_id,
            )
        return self._category_cache[lzt_category_id]

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of purchased accounts from LZT API.

        Incremental: pages forward from page 1 (newest first), stops
        when is_already_seen hits the last-known item_id.

        Backfill: not supported — raises NotImplementedError.
        """
        if checkpoint.mode == SyncMode.BACKFILL:
            raise NotImplementedError(
                "LZT backfill via fetch_page is not supported. "
                "Use: import_lzt_orders <account> --source api"
            )

        page = checkpoint.meta.get('_incremental_page', 1)

        result = self.provider.fetch_orders(
            self.client,
            params={'page': page},
        )

        if not result.ok:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"LZT API error on page {page}: {error_msg}"
            )

        order_page = result.data
        items = order_page.items if order_page else []

        if not items:
            return [], ''

        next_cursor = str(page + 1) if order_page.has_next_page else ''

        # Track page progression for incremental mode
        if next_cursor:
            checkpoint.meta = {
                **checkpoint.meta,
                '_incremental_page': page + 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

        return items, next_cursor

    def is_already_seen(self, item: dict, stop_remote_id: str) -> bool:
        if not stop_remote_id:
            return False
        return self.extract_remote_id(item) == stop_remote_id

    def extract_remote_id(self, item: dict) -> str:
        return mapper.extract_remote_id(item)

    def extract_remote_timestamp(self, item: dict):
        return mapper.extract_purchased_at(item)

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw LZT item and upsert into OwnedProduct.

        Uses the shared get_or_create_owned_product helper for canonical
        (category, login) identity. LZT-specific fields
        (source_product_id, raw_data) are filled after the shared upsert.
        """
        payload = raw_payload.payload

        parsed = mapper.to_parsed_credentials(payload)
        lzt_category_id = mapper.extract_category_id(payload)
        price, currency = mapper.extract_price(payload)
        purchased_at = mapper.extract_purchased_at(payload)

        category = self._get_category(lzt_category_id)

        owned = get_or_create_owned_product(
            parsed=parsed,
            category=category,
            game=None,
            source_account=raw_payload.integration_account,
            status=OwnedProductStatus.DRAFT,
            price=price,
            currency=currency,
            purchased_at=purchased_at,
        )

        if not owned:
            return None

        # LZT-specific fields: fill if empty (don't overwrite)
        update_fields = []
        if not owned.source_product_id:
            owned.source_product_id = int(raw_payload.remote_id)
            update_fields.append('source_product_id')
        if not owned.raw_data:
            owned.raw_data = payload
            update_fields.append('raw_data')
        if update_fields:
            owned.save(update_fields=update_fields + ['updated_at'])

        # source_product_id was empty → new record for LZT purposes
        return 'created' if 'source_product_id' in update_fields else 'updated'
