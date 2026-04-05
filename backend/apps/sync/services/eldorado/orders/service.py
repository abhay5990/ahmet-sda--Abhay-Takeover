from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.sync.enums import ResourceType, SyncMode

from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


class EldoradoOrderSyncService(BaseSyncService):
    """Order sync orchestration for Eldorado.

    Hooks used:
        - ``prepare_item``: conditional enrichment for instant account
          orders. Raises ``StopSync`` on enrichment failure (BD-2).
        - ``is_already_seen``: incremental stop condition via remote_id.

    Direction:
        - Backfill: ``oldest_first`` (chronological history build-up)
        - Incremental: ``newest_first`` (catch new orders, stop at known)
    """

    resource_type = ResourceType.ORDERS

    BACKFILL_DIRECTION = 'oldest_first'
    INCREMENTAL_DIRECTION = 'newest_first'

    _DIRECTION_CONFIG = {
        'newest_first': {
            'initial_cursor': (
                '9999-99-99 99:99:99.999999999999999'
                '-9999-9999-9999-999999999999'
            ),
            'page_direction': 'Next',
            'next_cursor_field': 'nextPageCursor',
        },
        'oldest_first': {
            'initial_cursor': (
                '0000-00-00 00:00:00.000000000000000'
                '-0000-0000-0000-000000000000'
            ),
            'page_direction': 'Previous',
            'next_cursor_field': 'previousPageCursor',
        },
    }

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client
        self._stop_timestamp = None

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of orders from Eldorado.

        Direction is determined by sync mode:
        backfill → oldest_first, incremental → newest_first.
        """
        # Snapshot the stop timestamp once for incremental mode
        if (
            checkpoint.mode == SyncMode.INCREMENTAL
            and self._stop_timestamp is None
            and checkpoint.last_seen_remote_timestamp
        ):
            self._stop_timestamp = checkpoint.last_seen_remote_timestamp

        direction = (
            self.INCREMENTAL_DIRECTION
            if checkpoint.mode == SyncMode.INCREMENTAL
            else self.BACKFILL_DIRECTION
        )
        cfg = self._DIRECTION_CONFIG[direction]
        cursor_value = checkpoint.cursor or cfg['initial_cursor']

        params = {
            'cursorValue': cursor_value,
            'pageSize': '20',
            'pageDirection': cfg['page_direction'],
            'isAscendingDateOrder': 'false',
            'ignorePendingReviewOrders': 'true',
            'displayFilter': 'DisplaySellingOrders',
            'orderGroup': 'Regular',
        }

        result = self.provider.fetch_orders(self.client, params=params)

        if not result.ok or result.data is None:
            return [], ''

        page = result.data
        items = [order.model_dump() for order in page.results]
        next_cursor = getattr(page, cfg['next_cursor_field'], None) or ''

        return items, next_cursor

    def extract_remote_id(self, item: dict) -> str:
        return str(item.get('id') or '').strip()

    def extract_remote_timestamp(self, item: dict):
        raw_ts = item.get('createdDate')
        if not raw_ts:
            return None
        try:
            return datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Stop incremental sync when we hit an already-seen order.

        Two stop conditions (whichever fires first):
        1. Exact remote_id match (primary)
        2. Order timestamp older than checkpoint timestamp (fallback)

        The timestamp fallback prevents full-table scans when the
        stop_remote_id order is buried deep in pagination.
        """
        if not stop_remote_id:
            return False

        # Primary: exact ID match
        if self.extract_remote_id(item) == stop_remote_id:
            return True

        # Fallback: timestamp-based stop
        if self._stop_timestamp:
            item_ts = self.extract_remote_timestamp(item)
            if item_ts and item_ts < self._stop_timestamp:
                logger.info(
                    "Timestamp-based stop: order %s (%s) is older "
                    "than checkpoint (%s)",
                    self.extract_remote_id(item),
                    item_ts.isoformat(),
                    self._stop_timestamp.isoformat(),
                )
                return True

        return False

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Enrich instant account orders with account details.

        Non-instant or non-account orders pass through unchanged.
        Enrichment failure raises ``StopSync`` per BD-2.
        """
        if not mapper.needs_enrichment(item):
            return item, {'enrichment': 'not_required'}

        enriched_item, enrich_meta = self._enrich_order(item)

        if enrich_meta.get('enrichment') == 'failed':
            logger.warning(
                "Enrichment failed for order %s, saving without account details: %s",
                item.get('id'),
                enrich_meta.get('enrichment_error', 'unknown'),
            )

        return enriched_item, enrich_meta

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw order payload and upsert into Order table."""
        payload = raw_payload.payload
        offer = payload.get('orderOfferDetails') or {}

        price = Decimal(
            str(payload.get('totalPrice', {}).get('amount', 0)),
        )
        currency = payload.get('totalPrice', {}).get('currency', 'USD')

        defaults = {
            'is_instant': offer.get('guaranteedDeliveryTime') == 'Instant',
            'product_category': mapper.map_category(offer.get('category')),
            'status': mapper.map_status(payload),
            'price': price,
            'currency': currency,
            'our_fee': self._extract_fee(payload),
            'sold_at': self.extract_remote_timestamp(payload),
            'store_listing_id': payload.get('offerId') or '',
            'raw_data': payload,
        }

        # Game resolve
        from apps.inventory.services import resolve_game
        game_ext_id = mapper.extract_game_external_id(payload)
        if game_ext_id:
            game = resolve_game('eldorado', game_ext_id)
            if game:
                defaults['game'] = game

        # OwnedProduct match-or-create
        owned = self._match_or_create_owned_product(
            payload, raw_payload, price, currency,
        )
        if owned:
            defaults['owned_product'] = owned

        return self._upsert_order(raw_payload, defaults)

    def _match_or_create_owned_product(
        self, payload: dict, raw_payload: RawPayload,
        price: Decimal, currency: str,
    ):
        """Match or create OwnedProduct from order credentials.

        Parses accountDetails.secretDetails via shared parser,
        creates OwnedProduct if none exists with status=SOLD.
        """
        from apps.inventory.enums import OwnedProductStatus
        from apps.inventory.services import resolve_game
        from apps.sync.services.shared.owned_product import get_or_create_owned_product

        parsed = mapper.parse_credentials_from_account_details(payload)
        if not parsed.login:
            return None

        game_ext_id = mapper.extract_game_external_id(payload)
        if not game_ext_id:
            return None

        game = resolve_game('eldorado', game_ext_id)
        if not game or not game.category:
            return None

        sold_at = self.extract_remote_timestamp(payload)
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

    # ── Private helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_fee(payload: dict) -> Decimal | None:
        fees = (payload.get('sellerPayments') or {}).get('sellerFees')
        if fees and fees.get('amount') is not None:
            return Decimal(str(fees['amount']))
        return None

    def _enrich_order(self, item: dict) -> tuple[dict, dict]:
        """Fetch and merge account details into the order.

        Returns ``(enriched_item, enrich_meta)``.
        On failure: item is returned as-is with failure meta.
        """
        order_id = item.get('id', '')
        try:
            result = self.provider.fetch_order_account_details(
                self.client, order_id,
            )

            if not result.ok or result.data is None:
                error_msg = ''
                if hasattr(result, 'error') and result.error:
                    error_msg = getattr(
                        result.error, 'message', str(result.error),
                    )
                return item, {
                    'enrichment': 'failed',
                    'enrichment_error': error_msg or 'empty response',
                }

            if hasattr(result.data, 'model_dump'):
                item['accountDetails'] = result.data.model_dump()
            else:
                item['accountDetails'] = result.data

            return item, {'enrichment': 'completed'}

        except Exception as exc:
            logger.warning(
                "Enrichment failed for order %s: %s", order_id, exc,
            )
            return item, {
                'enrichment': 'failed',
                'enrichment_error': str(exc),
            }
