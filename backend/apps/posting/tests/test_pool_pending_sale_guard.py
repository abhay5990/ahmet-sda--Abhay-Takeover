from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.posting.services.pool.allocation import (
    _FINAL_SALE_ORDER_STATUSES,
    claim_pending_items,
)


class PendingSaleGuardTests(SimpleTestCase):
    @patch("apps.posting.services.pool.allocation.transaction.atomic")
    @patch("apps.posting.services.pool.allocation.PoolOffer.objects")
    @patch("apps.posting.services.pool.allocation.OfferPoolItem.objects")
    def test_claim_excludes_pending_items_with_exact_final_order(
        self,
        item_objects,
        pool_offer_objects,
        atomic,
    ):
        atomic.return_value = nullcontext()
        locked_offer = SimpleNamespace(pk=81, pool_id=44, can_replenish=True)
        pool_offer_objects.select_for_update.return_value.select_related.return_value.get.return_value = locked_offer

        items_qs = MagicMock()
        item_objects.filter.return_value = items_qs
        items_qs.exclude.return_value = items_qs
        items_qs.select_related.return_value = items_qs
        items_qs.order_by.return_value = items_qs
        items_qs.__getitem__.return_value = []

        self.assertEqual(claim_pending_items(SimpleNamespace(pk=81), 1), [])

        items_qs.exclude.assert_called_once_with(
            owned_product__orders__status__in=_FINAL_SALE_ORDER_STATUSES,
        )
