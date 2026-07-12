"""GameBoost item order sync service.

Polls the GameBoost /item-orders endpoint and upserts them as Order records,
linking each order to its DropshipProduct via store_listing_id = item_offer_id.
"""
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


class GameboostItemOrderSyncService(BaseSyncService):
    """Order sync for GameBoost item orders (SAB, New World, etc.).

    Uses page-based pagination. Maps item_offer_id as store_listing_id
    so orders are automatically linked to DropshipProduct via _link_listing.
    """

    resource_type = ResourceType.ITEM_ORDERS
    DEFAULT_PAGE_SIZE = 15
    BACKFILL_SORT = 'created_at'
    INCREMENTAL_SORT = '-updated_at'

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of item orders using page-based pagination."""
        if checkpoint.mode == SyncMode.INCREMENTAL:
            page = checkpoint.meta.get('_incremental_page', 1)
            sort = self.INCREMENTAL_SORT
        else:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1
            sort = self.BACKFILL_SORT

        result = self.provider.fetch_item_orders(
            self.client,
            params={
                'page': page,
                'per_page': self.DEFAULT_PAGE_SIZE,
                'sort': sort,
            },
        )
        if not result.ok:
            error_msg = result.error.message if result.error else ''
            raise RuntimeError(
                f"Gameboost item orders API error on page {page}: {error_msg}"
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

        pagination = result.meta.get('pagination', {})
        current_page = pagination.get('current_page', page)
        last_page = pagination.get('last_page', current_page)
        next_cursor = str(current_page + 1) if current_page < last_page else ''

        if checkpoint.mode == SyncMode.INCREMENTAL and next_cursor:
            checkpoint.meta = {
                **checkpoint.meta,
                '_incremental_page': current_page + 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

        return items, next_cursor

    def is_already_seen(self, item: dict, stop_remote_id: str) -> bool:
        if not stop_remote_id:
            return False
        return str(item.get('id') or '').strip() == stop_remote_id

    def extract_remote_id(self, item: dict) -> str:
        return str(item.get('id') or '').strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_unix_timestamp(
            item.get('updated_at') or item.get('created_at')
        )

    def prepare_item(self, item: dict, account: IntegrationAccount) -> tuple[dict, dict]:
        return item, {}

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw GameBoost item order and upsert into Order table."""
        payload = raw_payload.payload

        # Extract price from item order (price_eur/price_usd may be dicts or strings)
        price_value, currency = self._extract_item_order_price(payload)

        # item_offer_id is the store_listing_id — links to DropshipProduct
        item_offer_id = payload.get('item_offer_id')
        store_listing_id = str(item_offer_id) if item_offer_id else ''

        defaults = {
            'is_instant': False,  # item orders are manual delivery
            'product_category': 'item',
            'status': mapper.map_status(payload.get('status', '')),
            'price': Decimal(str(price_value)),
            'currency': currency,
            'our_fee': None,
            'sold_at': mapper.parse_unix_timestamp(
                payload.get('purchased_at') or payload.get('created_at'),
            ),
            'store_listing_id': store_listing_id,
            'raw_data': payload,
        }

        # Game resolve
        from apps.inventory.services import resolve_game
        game_ext_id = str(payload.get('game', {}).get('id') or '') if isinstance(payload.get('game'), dict) else ''
        if game_ext_id:
            game = resolve_game('gameboost', game_ext_id)
            if game:
                defaults['game'] = game

        return self._upsert_order(raw_payload, defaults)

    @staticmethod
    def _extract_item_order_price(payload: dict) -> tuple[float, str]:
        """Extract price from item order. price_usd/price_eur may be dicts or strings."""
        price_usd = payload.get('price_usd')
        if isinstance(price_usd, dict) and price_usd.get('value') is not None:
            return float(price_usd['value']), 'USD'
        if isinstance(price_usd, str) and price_usd:
            try:
                return float(price_usd), 'USD'
            except (ValueError, TypeError):
                pass

        price_eur = payload.get('price_eur')
        if isinstance(price_eur, dict) and price_eur.get('value') is not None:
            return float(price_eur['value']), 'EUR'
        if isinstance(price_eur, str) and price_eur:
            try:
                return float(price_eur), 'EUR'
            except (ValueError, TypeError):
                pass

        return 0.0, 'USD'
