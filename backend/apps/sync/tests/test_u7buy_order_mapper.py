from django.test import SimpleTestCase

from apps.orders.enums import OrderStatus
from apps.sync.services.u7buy.orders import mapper


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
