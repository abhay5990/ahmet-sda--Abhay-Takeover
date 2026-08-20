from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.sync.services.playerauctions.orders.service import (
    PlayerAuctionsOrderSyncService,
)


class PlayerAuctionsOneOrderRecoveryTests(SimpleTestCase):
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
