import json
from decimal import Decimal

from django.test import SimpleTestCase

from apps.posting.services.pa_edit_queue import _json_safe_changes


class PlayerAuctionsEditQueueSerializationTests(SimpleTestCase):
    def test_decimal_price_is_json_safe_without_losing_its_exact_value(self):
        changes = _json_safe_changes(
            {
                "title": "Updated title",
                "description": "Updated description",
                "price": Decimal("34.90"),
            }
        )

        self.assertEqual(changes["price"], "34.90")
        self.assertEqual(changes["title"], "Updated title")
        self.assertEqual(changes["description"], "Updated description")
        json.dumps(changes)
