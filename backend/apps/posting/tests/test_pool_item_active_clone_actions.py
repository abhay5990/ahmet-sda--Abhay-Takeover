from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.listings.enums import ListingStatus
from apps.posting.models import OfferPoolActiveOfferStatus
from apps.posting.views import _build_pool_item_views


class PoolItemActiveCloneActionTests(SimpleTestCase):
    def test_item_row_prefers_live_clone_over_historical_failed_clone(self):
        item = SimpleNamespace(
            pk=1,
            pool_offer_id=9,
            target_offer_id='294600001',
            status='pushed',
            owned_product=SimpleNamespace(ref_key='', login='account@example.com'),
            consumed_at=None,
        )
        listing = SimpleNamespace(store_listing_id='294600001', title='GTA V #ABC123')
        pool_offer = SimpleNamespace(pk=9, store=None, marketplace='playerauctions', listing=listing)
        failed = SimpleNamespace(
            pool_item_id=1,
            pool_offer_id=9,
            status=OfferPoolActiveOfferStatus.FAILED,
            listing=SimpleNamespace(store_listing_id='old', title='old'),
            listing_id=1,
        )
        active = SimpleNamespace(
            pool_item_id=1,
            pool_offer_id=9,
            status=OfferPoolActiveOfferStatus.ACTIVE,
            listing=listing,
            listing_id=2,
        )

        _, _, _, _, all_rows = _build_pool_item_views(
            [pool_offer],
            [item],
            [failed, active],
            [],
        )

        row = all_rows[0]
        self.assertIs(row['active_clone'], active)
        self.assertIs(row['relistable_pa_clone'], active)
        self.assertEqual(row['offer_id'], '294600001')

    def test_item_row_does_not_mark_closed_delisted_pa_clone_relistable(self):
        item = SimpleNamespace(
            pk=1,
            pool_offer_id=9,
            target_offer_id='294600002',
            status='pushed',
            owned_product=SimpleNamespace(ref_key='', login='closed@example.com'),
            consumed_at=None,
        )
        listing = SimpleNamespace(
            store_listing_id='294600002',
            title='GTA V #ABC124',
            status=ListingStatus.CLOSED,
        )
        pool_offer = SimpleNamespace(pk=9, store=None, marketplace='playerauctions', listing=listing)
        delisted = SimpleNamespace(
            pool_item_id=1,
            pool_offer_id=9,
            status=OfferPoolActiveOfferStatus.DELISTED,
            listing=listing,
            listing_id=2,
        )

        _, _, _, _, all_rows = _build_pool_item_views(
            [pool_offer],
            [item],
            [delisted],
            [],
        )

        self.assertIsNone(all_rows[0]['relistable_pa_clone'])
