from __future__ import annotations

from typing import TYPE_CHECKING

from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import SyncCheckpoint

from .service import EldoradoOrderSyncService

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount


class EldoradoHistoricalOrderSyncService(EldoradoOrderSyncService):
    """Fetches orders from the Eldorado 'Historical' order group (>3 months old).

    Identical to the regular order sync but uses orderGroup=Historical.
    Intended as a one-time backfill — no incremental mode needed.
    """

    resource_type = ResourceType.HISTORICAL_ORDERS

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        cfg = self._DIRECTION_CONFIG[self.BACKFILL_DIRECTION]
        cursor_value = checkpoint.cursor or cfg['initial_cursor']

        params = {
            'cursorValue': cursor_value,
            'pageSize': '20',
            'pageDirection': cfg['page_direction'],
            'isAscendingDateOrder': 'false',
            'ignorePendingReviewOrders': 'true',
            'displayFilter': 'DisplaySellingOrders',
            'orderGroup': 'Historical',
        }

        result = self.provider.fetch_orders(self.client, params=params)

        if not result.ok or result.data is None:
            return [], ''

        page = result.data
        items = [order.model_dump() for order in page.results]
        next_cursor = getattr(page, cfg['next_cursor_field'], None) or ''

        return items, next_cursor
