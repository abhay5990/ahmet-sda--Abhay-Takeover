from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


class GameboostOrderSyncService(BaseSyncService):
    """Order sync orchestration for Gameboost.

    Uses page-based pagination via ``ApiResult.meta["pagination"]``.

    Direction:
        - Backfill: ``created_at`` ascending (oldest first)
        - Incremental: ``-updated_at`` descending (newest first)

    Price: Uses ``price_usd.value`` as canonical. Falls back to
    ``price.value`` (EUR) if USD is not present.
    """

    resource_type = ResourceType.ORDERS

    DEFAULT_PAGE_SIZE = 15
    BACKFILL_SORT = 'created_at'
    INCREMENTAL_SORT = '-updated_at'

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of orders using page-based pagination.

        Backfill: resumes from checkpoint cursor (page number).
        Incremental: starts from page 1, tracks page in meta.
        """
        if checkpoint.mode == SyncMode.INCREMENTAL:
            page = checkpoint.meta.get('_incremental_page', 1)
            sort = self.INCREMENTAL_SORT
        else:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1
            sort = self.BACKFILL_SORT

        result = self.provider.fetch_orders(
            self.client,
            params={
                'page': page,
                'per_page': self.DEFAULT_PAGE_SIZE,
                'sort': sort,
            },
        )

        if not result.ok:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"Gameboost API error on page {page}: {error_msg}"
            )

        items: list[dict] = []
        for order in result.data or []:
            if hasattr(order, 'model_dump'):
                items.append(order.model_dump())
            elif isinstance(order, dict):
                items.append(order)
            else:
                items.append(dict(order))

        if not items:
            return [], ''

        # Determine next page from pagination metadata
        pagination = result.meta.get('pagination', {})
        current_page = pagination.get('current_page', page)
        last_page = pagination.get('last_page', current_page)

        next_cursor = str(current_page + 1) if current_page < last_page else ''

        # Track page progression for incremental mode
        if checkpoint.mode == SyncMode.INCREMENTAL and next_cursor:
            checkpoint.meta = {
                **checkpoint.meta,
                '_incremental_page': current_page + 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

        return items, next_cursor

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Stop incremental sync when we hit an already-seen order."""
        if not stop_remote_id:
            return False
        return str(item.get('id') or '').strip() == stop_remote_id

    def extract_remote_id(self, item: dict) -> str:
        return str(item.get('id') or '').strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_unix_timestamp(
            item.get('purchased_at') or item.get('created_at'),
        )

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Enrich account orders with credentials from the API.

        Gameboost's new system stores credentials separately.
        For instant account orders where credentials is null,
        fetch via GET /account-offers/{offer_id}/credentials
        and match by account_order_id.
        """
        # Only enrich instant account orders with missing credentials
        if item.get('is_manual_delivery', False):
            return item, {}
        if item.get('credentials'):
            return item, {'credentials_source': 'inline'}
        offer_id = item.get('account_offer_id')
        if not offer_id:
            return item, {}

        order_id = item.get('id')

        try:
            result = self.client.list_offer_credentials(
                account_id=str(offer_id),
            )
            if result.ok and result.data:
                entries = []
                matched_entry = None
                for entry in result.data:
                    if hasattr(entry, 'model_dump'):
                        d = entry.model_dump()
                    elif isinstance(entry, dict):
                        d = entry
                    else:
                        d = dict(entry)
                    entries.append(d)

                    if order_id and d.get('account_order_id') == order_id:
                        matched_entry = d

                if matched_entry:
                    item = {
                        **item,
                        '_credential_entries': [matched_entry],
                    }
                    return item, {'credentials_source': 'api'}

                # No exact match by order_id — store all entries
                item = {**item, '_credential_entries': entries}
                return item, {'credentials_source': 'api_no_exact_match'}

            logger.warning(
                "No credentials returned for order %s (offer %s)",
                order_id, offer_id,
            )
            return item, {'credentials_source': 'api_empty'}

        except Exception as exc:
            logger.warning(
                "Credentials fetch failed for order %s (offer %s): %s",
                order_id, offer_id, exc,
            )
            return item, {
                'credentials_source': 'api_failed',
                'credentials_error': str(exc),
            }

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw Gameboost order payload and upsert into Order table."""
        payload = raw_payload.payload
        price_value, currency = mapper.extract_price_usd(payload)

        defaults = {
            'is_instant': not payload.get('is_manual_delivery', False),
            'product_category': mapper.map_category(payload),
            'status': mapper.map_status(payload.get('status', '')),
            'price': Decimal(str(price_value)),
            'currency': currency,
            'our_fee': None,
            'sold_at': mapper.parse_unix_timestamp(
                payload.get('purchased_at') or payload.get('created_at'),
            ),
            'store_listing_id': mapper.extract_listing_id(payload),
            'raw_data': payload,
        }

        # Game resolve
        from apps.inventory.services import resolve_game
        game_ext_id = mapper.extract_game_external_id(payload)
        if game_ext_id:
            game = resolve_game('gameboost', game_ext_id)
            if game:
                defaults['game'] = game

        # OwnedProduct match-or-create
        owned = self._match_or_create_owned_product(
            payload, raw_payload, Decimal(str(price_value)), currency,
        )
        if owned:
            defaults['owned_product'] = owned

        return self._upsert_order(raw_payload, defaults)

    def _match_or_create_owned_product(
        self, payload: dict, raw_payload: RawPayload,
        price: Decimal, currency: str,
    ):
        """Match or create OwnedProduct from order credentials.

        Tries credential entries (new API) first, falls back to
        inline credentials string (legacy). Creates OwnedProduct
        if none exists with status=SOLD.
        """
        from apps.inventory.enums import OwnedProductStatus
        from apps.inventory.services import resolve_game
        from apps.sync.services.shared.owned_product import get_or_create_owned_product

        # Parse full credentials — 3-step fallback:
        # 1. _credential_entries (API entries, free text → shared parser)
        # 2. credentials (inline string → shared parser)
        # 3. delivery_instructions (free text → shared parser)
        parsed = None
        entries = payload.get('_credential_entries') or []
        if entries:
            parsed_list = mapper.parse_credentials_from_entries(entries)
            if parsed_list:
                parsed = parsed_list[0]

        if not parsed or not parsed.login:
            parsed = mapper.parse_credentials_from_inline(payload)

        if not parsed or not parsed.login:
            parsed = mapper.parse_credentials_from_delivery_instructions(payload)

        if not parsed or not parsed.login:
            return None

        game_ext_id = mapper.extract_game_external_id(payload)
        if not game_ext_id:
            return None

        game = resolve_game('gameboost', game_ext_id)
        if not game or not game.category:
            return None

        sold_at = mapper.parse_unix_timestamp(
            payload.get('purchased_at') or payload.get('created_at'),
        )

        # Price / 2 as cost estimate
        cost = price / 2 if price else None

        return get_or_create_owned_product(
            parsed=parsed,
            category=game.category,
            game=game,
            source_account=raw_payload.integration_account,
            status=OwnedProductStatus.SOLD,
            price=cost,
            currency=currency,
            purchased_at=sold_at,
            raw_data=payload,
        )
