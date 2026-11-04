"""Expired Mart PA pool clones return to their pool (4 Nov 2026 incident).

Before: one expired clone froze the whole pool forever ("Mart snapshot did not
confirm … skipping replenishment"). After: a clone missing from a fresh
snapshot whose own expiry passed (+2h grace) and that has no sale/order/
reservation evidence goes back to the pool; everything else stays fail-closed.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolOfferStrategy,
)
from apps.posting.services.pool.checker import _get_pa_active_count
from apps.posting.services.pool.replenisher import _PoolOfferContext
from apps.posting.tests.test_unified_offer_pool import UnifiedPoolTestCase


class ExpiredMartPoolReturnTests(UnifiedPoolTestCase):
    def setUp(self):
        self.mart = IntegrationAccount.objects.create(
            name='Mart', slug='playerauctions-csgosmurfkings', provider='playerauctions', role='sell',
        )
        IntegrationCredential.objects.create(account=self.mart, credentials={'test': 'credential'})
        self.pool = self.make_pool('Mart Pool')
        self.template = self.make_listing(account=self.mart, remote_id='294000000')
        self.pool_offer = self.make_pool_offer(
            self.pool, listing=self.template, strategy=PoolOfferStrategy.CLONE,
            target_count=1, threshold=1, max_concurrent=1,
        )
        self.n = 0

    def clone(self, *, expired_hours_ago):
        self.n += 1
        offer_id = str(295000000 + self.n)
        listing = self.make_listing(account=self.mart, remote_id=offer_id)
        listing.marketplace_expires_at = timezone.now() - timedelta(hours=expired_hours_ago)
        listing.save(update_fields=['marketplace_expires_at'])
        product = self.make_owned(f'mart-{self.n}@example.test')
        listing.listing_owned_products.create(owned_product=product)
        item = OfferPoolItem.objects.create(
            pool=self.pool, pool_offer=self.pool_offer, owned_product=product,
            status=OfferPoolItemStatus.PUSHED, target_offer_id=offer_id,
        )
        ao = OfferPoolActiveOffer.objects.create(
            pool=self.pool, pool_offer=self.pool_offer, listing=listing, pool_item=item,
            store_listing_id=offer_id, status=OfferPoolActiveOfferStatus.ACTIVE,
        )
        return ao

    def check(self, live_ids=(), age=60):
        client = Mock()
        client.uses_mct_official_offer_snapshot.return_value = True
        client.list_offers.return_value = SimpleNamespace(
            ok=True, data=[{'offerId': i} for i in live_ids], meta={'snapshot_age_seconds': age},
        )
        with patch('apps.posting.services.pool.checker.get_or_build_client', return_value=client):
            return _get_pa_active_count(_PoolOfferContext(self.pool_offer))

    def assert_returned(self, ao):
        ao.refresh_from_db()
        ao.pool_item.refresh_from_db()
        ao.listing.refresh_from_db()
        self.assertEqual(ao.status, OfferPoolActiveOfferStatus.FAILED)
        self.assertEqual(ao.pool_item.status, OfferPoolItemStatus.PENDING)
        self.assertIsNone(ao.pool_item.pool_offer_id)
        self.assertEqual(ao.pool_item.target_offer_id, '')
        self.assertEqual(ao.listing.status, 'closed')
        self.assertFalse(ao.listing.listing_owned_products.exists())

    def assert_untouched(self, ao):
        ao.refresh_from_db()
        ao.pool_item.refresh_from_db()
        self.assertEqual(ao.status, OfferPoolActiveOfferStatus.ACTIVE)
        self.assertEqual(ao.pool_item.status, OfferPoolItemStatus.PUSHED)

    def test_expired_unsold_clone_returns_to_pool_and_unfreezes_the_pool(self):
        ao = self.clone(expired_hours_ago=48)
        self.assertEqual(self.check(), 0)  # 0 live → normal threshold refill runs
        self.assert_returned(ao)

    def test_live_clone_is_kept_and_only_the_expired_one_returns(self):
        live = self.clone(expired_hours_ago=-240)
        dead = self.clone(expired_hours_ago=72)
        self.assertEqual(self.check(live_ids=[live.store_listing_id]), 1)
        self.assert_untouched(live)
        self.assert_returned(dead)

    def test_recently_expired_clone_waits_for_grace(self):
        ao = self.clone(expired_hours_ago=1)
        self.assertIsNone(self.check())
        self.assert_untouched(ao)

    def test_missing_but_not_expired_stays_fail_closed(self):
        ao = self.clone(expired_hours_ago=-100)
        self.assertIsNone(self.check())
        self.assert_untouched(ao)

    def test_no_recorded_expiry_stays_fail_closed(self):
        ao = self.clone(expired_hours_ago=48)
        ao.listing.marketplace_expires_at = None
        ao.listing.save(update_fields=['marketplace_expires_at'])
        self.assertIsNone(self.check())
        self.assert_untouched(ao)

    def test_stale_snapshot_never_returns_anything(self):
        ao = self.clone(expired_hours_ago=48)
        self.assertIsNone(self.check(age=5_000))
        self.assert_untouched(ao)

    def test_order_on_the_account_blocks_return(self):
        ao = self.clone(expired_hours_ago=48)
        Order.objects.create(
            integration_account=self.mart, store_listing_id=ao.store_listing_id,
            owned_product=ao.pool_item.owned_product,
        )
        self.assertIsNone(self.check())
        self.assert_untouched(ao)
