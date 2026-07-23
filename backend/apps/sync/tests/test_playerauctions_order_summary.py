from unittest.mock import Mock

from django.test import SimpleTestCase

from apis_sdk.clients.marketplaces.playerauctions.models import (
    PlayerAuctionsOrderListItem,
)
from apps.sync.services.playerauctions.orders.service import (
    PlayerAuctionsOrderSyncService,
)


class PlayerAuctionsOrderSummaryTests(SimpleTestCase):
    def test_seller_order_summary_preserves_offer_id(self):
        order = PlayerAuctionsOrderListItem.model_validate(
            {
                "orderId": 16306133,
                "offerId": 292889759,
                "orderTitle": "Fortnite account",
                "status": "Pending Buyer Inspection",
            }
        )

        payload = order.model_dump()

        self.assertEqual(payload["order_id"], 16306133)
        self.assertEqual(payload["offer_id"], 292889759)

    def test_prepare_item_uses_verified_summary_without_detail_request(self):
        service = PlayerAuctionsOrderSyncService()
        summary = {
            "order_id": 16306133,
            "offer_id": 292889759,
            "order_title": "Fortnite account",
            "status": "Pending Buyer Inspection",
        }
        service._fetch_and_merge_detail = Mock(
            side_effect=AssertionError("detail endpoint must not be called")
        )

        prepared, metadata = service.prepare_item(summary, account=Mock())

        self.assertEqual(prepared, summary)
        self.assertEqual(prepared["offer_id"], 292889759)
        self.assertEqual(metadata, {})
