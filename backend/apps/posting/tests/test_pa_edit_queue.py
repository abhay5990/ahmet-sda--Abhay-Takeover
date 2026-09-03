import json
from decimal import Decimal

from django.test import SimpleTestCase

from apps.posting.services.pa_edit_queue import _json_safe_changes
from apps.posting.services.offer_editor import BulkEditResult


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


class PlayerAuctionsEditQueueStatusTests(SimpleTestCase):
    def test_queued_edit_is_not_counted_as_marketplace_success(self):
        result = BulkEditResult(
            total=1,
            succeeded=0,
            queued=1,
            failed=0,
            queue_request_ids=[42],
        )

        self.assertEqual(result.total, 1)
        self.assertEqual(result.succeeded, 0)
        self.assertEqual(result.queued, 1)
        self.assertEqual(result.queue_request_ids, [42])
