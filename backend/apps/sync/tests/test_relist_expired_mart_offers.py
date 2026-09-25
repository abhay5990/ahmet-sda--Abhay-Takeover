from django.test import SimpleTestCase

from apps.sync.management.commands.relist_expired_mart_offers import (
    _chunked,
    _snapshot_is_fresh,
)


class RelistExpiredMartOfferCommandTests(SimpleTestCase):
    def test_snapshot_age_must_be_known_nonnegative_and_within_limit(self):
        self.assertTrue(_snapshot_is_fresh(0, 600))
        self.assertTrue(_snapshot_is_fresh("599", 600))
        self.assertFalse(_snapshot_is_fresh(None, 600))
        self.assertFalse(_snapshot_is_fresh(-1, 600))
        self.assertFalse(_snapshot_is_fresh(601, 600))

    def test_snapshot_queries_are_bounded(self):
        values = [str(value) for value in range(205)]
        batches = list(_chunked(values, 100))
        self.assertEqual([len(batch) for batch in batches], [100, 100, 5])
        self.assertEqual(batches[0][0], "0")
        self.assertEqual(batches[-1][-1], "204")
