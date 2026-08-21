from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.sync.services.playerauctions.orders.service import (
    PlayerAuctionsOrderSyncService,
)
from apps.sync.services.playerauctions.orders.mapper import extract_listing_id_from_detail


class PlayerAuctionsOneOrderRecoveryTests(SimpleTestCase):
    def test_list_payload_top_level_offer_id_is_used_for_listing_linkage(self):
        self.assertEqual(
            extract_listing_id_from_detail({"order_id": "16408663", "offer_id": "294161691"}),
            "294161691",
        )

    def test_bounded_scan_avoids_unsupported_order_id_parameter(self):
        provider = Mock()
        client = Mock()
        first_page = [
            {"orderId": str(index)} for index in range(1, 51)
        ]
        provider.fetch_orders.side_effect = [
            SimpleNamespace(ok=True, data=first_page),
            SimpleNamespace(ok=True, data=[{"orderId": "16408663"}]),
        ]
        service = PlayerAuctionsOrderSyncService(
            provider=provider,
            client=client,
        )

        matched = service._find_recent_order_for_recovery("16408663")

        self.assertEqual(matched["orderId"], "16408663")
        self.assertEqual(provider.fetch_orders.call_count, 2)
        for call in provider.fetch_orders.call_args_list:
            self.assertNotIn("order_id", call.kwargs)
            self.assertEqual(call.kwargs["page_size"], 50)

    def test_detail_enrichment_preserves_summary_fields_and_adds_login_evidence(self):
        provider = Mock()
        provider.fetch_order_details.return_value = SimpleNamespace(
            ok=True,
            data={
                "orderInfo": {"loginName": "cbtkngg3uzb", "offerId": "294436960"},
                "status": {"current": "Pending Buyer Inspection"},
            },
        )
        service = PlayerAuctionsOrderSyncService(provider=provider, client=Mock())

        merged = service._fetch_and_merge_detail(
            {
                "orderId": "16407126",
                "createTime": "Aug-20-2026 09:00:00 PM",
                "productType": "Accounts",
            },
            "16407126",
        )

        self.assertEqual(merged["orderInfo"]["loginName"], "cbtkngg3uzb")
        self.assertEqual(merged["createTime"], "Aug-20-2026 09:00:00 PM")
        self.assertEqual(merged["productType"], "Accounts")
