from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.orders.enums import OrderStatus
from apps.sync.services.u7buy.orders import mapper
from apps.sync.services.u7buy.orders.service import U7BuyOrderSyncService


class U7BuyOrderMapperTests(SimpleTestCase):
    def test_only_documented_sale_states_are_confirmed(self):
        self.assertEqual(mapper.map_status({"orderStatus": 2}), OrderStatus.PENDING)
        self.assertEqual(mapper.map_status({"orderStatus": 4}), OrderStatus.PENDING)
        self.assertEqual(mapper.map_status({"orderStatus": 5}), OrderStatus.COMPLETED)
        self.assertEqual(mapper.map_status({"orderStatus": 6}), OrderStatus.CANCELLED)

    def test_extracts_u7buy_offer_and_order_identifiers(self):
        payload = {"orderId": 42, "productId": 99, "gameId": 13}
        self.assertEqual(mapper.extract_remote_id(payload), "42")
        self.assertEqual(mapper.extract_listing_id(payload), "99")
        self.assertEqual(mapper.extract_game_external_id(payload), "13")

    def test_parses_millisecond_timestamp(self):
        timestamp = mapper.parse_timestamp(1_700_000_000_000)
        self.assertIsNotNone(timestamp)
        self.assertEqual(timestamp.year, 2023)


class U7BuyAutomaticOrderTests(SimpleTestCase):
    def test_only_locally_marked_automatic_offer_is_instant(self):
        account = SimpleNamespace(provider="u7buy")
        raw_payload = SimpleNamespace(integration_account=account)
        listing = SimpleNamespace(raw_data={
            "payload": {"_u7buy_delivery_mode": "automatic"},
        })
        first = Mock(return_value=listing)
        only = Mock()
        only.first = first
        filtered = Mock()
        filtered.only.return_value = only

        with patch("apps.listings.models.Listing.objects.filter", return_value=filtered):
            self.assertTrue(
                U7BuyOrderSyncService._is_managed_automatic_offer(
                    raw_payload,
                    {"productId": "offer-1"},
                )
            )

    def test_manual_or_unknown_offer_stays_non_instant(self):
        account = SimpleNamespace(provider="u7buy")
        raw_payload = SimpleNamespace(integration_account=account)
        listing = SimpleNamespace(raw_data={
            "payload": {"_u7buy_delivery_mode": "manual"},
        })
        first = Mock(return_value=listing)
        only = Mock()
        only.first = first
        filtered = Mock()
        filtered.only.return_value = only

        with patch("apps.listings.models.Listing.objects.filter", return_value=filtered):
            self.assertFalse(
                U7BuyOrderSyncService._is_managed_automatic_offer(
                    raw_payload,
                    {"productId": "offer-1"},
                )
            )
