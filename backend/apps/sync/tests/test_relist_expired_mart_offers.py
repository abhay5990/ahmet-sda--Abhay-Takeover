from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.inventory.enums import OwnedProductStatus
from apps.posting.services.relist import _restore_draft_owned_products_after_bulk_link
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


class RelistLifecyclePreservationTests(SimpleTestCase):
    def test_bulk_link_restore_marks_only_draft_inventory_listed(self):
        query = Mock()
        query.update.return_value = 2
        model = SimpleNamespace(objects=Mock())
        model.objects.filter.return_value = query

        restored = _restore_draft_owned_products_after_bulk_link(
            [101, 102], owned_product_model=model,
        )

        self.assertEqual(restored, 2)
        model.objects.filter.assert_called_once_with(
            pk__in=[101, 102], status=OwnedProductStatus.DRAFT,
        )
        query.update.assert_called_once_with(status=OwnedProductStatus.LISTED)

    def test_bulk_link_restore_skips_empty_inventory(self):
        model = SimpleNamespace(objects=Mock())

        self.assertEqual(
            _restore_draft_owned_products_after_bulk_link([], owned_product_model=model),
            0,
        )
        model.objects.filter.assert_not_called()
