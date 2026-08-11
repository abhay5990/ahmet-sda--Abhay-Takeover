"""A verified marketplace sale must mark the pool item CONSUMED.

Previously ``_record_sale_event`` flipped a PA clone to SOLD (or decremented an
append offer's count) but left the linked ``OfferPoolItem`` PUSHED, so the sold
account never showed as sold on the pool page and could be re-offered or
double-counted. This asserts the item is now consumed for both PA clones and
append offers, and that the transition is idempotent.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
    PoolSaleEvent,
)
from apps.posting.services.pool.checker import _record_sale_event


class ConsumeItemOnSaleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="rc", title="RC")
        cls.game = Game.objects.create(
            name="GTA", slug="grand-theft-auto-5", category=cls.category,
        )

    def _store(self, provider, slug):
        return IntegrationAccount.objects.create(
            name=slug, slug=slug, provider=provider, role="sell",
        )

    def _pool(self, store, *, strategy, marketplace_offer_id="offer-1"):
        pool = OfferPool.objects.create(
            name="P", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        listing = Listing.objects.create(
            is_instant=True, integration_account=store, game=self.game,
            store_listing_id=marketplace_offer_id, status="listed",
            title=marketplace_offer_id, price=Decimal("10.00"), currency="USD",
        )
        pool_offer = PoolOffer.objects.create(
            pool=pool, listing=listing, strategy=strategy,
            target_count=2, threshold=1, status=PoolOfferStatus.ACTIVE,
            max_concurrent=5 if strategy == PoolOfferStrategy.CLONE else None,
        )
        return pool, listing, pool_offer

    def _owned(self, login):
        return OwnedProduct.objects.create(
            category=self.category, game=self.game,
            login=login, password="pw", status="listed",
        )

    def _item(self, pool, pool_offer, owned, status=OfferPoolItemStatus.PUSHED, order=0):
        return OfferPoolItem.objects.create(
            pool=pool, pool_offer=pool_offer, owned_product=owned,
            status=status, remote_state="present", order=order,
        )

    def _order(self, store, owned, store_order_id):
        return Order.objects.create(
            integration_account=store, store_order_id=store_order_id,
            owned_product=owned, status=OrderStatus.COMPLETED,
            price=Decimal("20.00"), currency="USD", sold_at=timezone.now(),
        )

    def test_pa_clone_sale_marks_active_offer_sold_and_item_consumed(self):
        store = self._store("playerauctions", "pa-store")
        pool, listing, pool_offer = self._pool(store, strategy=PoolOfferStrategy.CLONE)
        owned = self._owned("pa-acct")
        item = self._item(pool, pool_offer, owned)
        clone = OfferPoolActiveOffer.objects.create(
            pool=pool, pool_offer=pool_offer, listing=listing,
            store_listing_id="pa-clone-1", pool_item=item,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        )
        order = self._order(store, owned, "PA-1")

        _record_sale_event(
            pool_offer, listing_id=listing.pk, event_key="pa:1",
            order_id=order.pk, active_offer=clone,
        )

        clone.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(clone.status, OfferPoolActiveOfferStatus.SOLD)
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)
        self.assertEqual(item.remote_state, "sold")
        self.assertIsNotNone(item.consumed_at)
        self.assertTrue(
            PoolSaleEvent.objects.filter(pool_item=item, order_id=order.pk).exists()
        )

    def test_pa_clone_delisted_by_sweep_is_recovered_and_consumed(self):
        store = self._store("playerauctions", "pa-store2")
        pool, listing, pool_offer = self._pool(store, strategy=PoolOfferStrategy.CLONE)
        owned = self._owned("pa-acct2")
        item = self._item(pool, pool_offer, owned, status=OfferPoolItemStatus.FAILED)
        clone = OfferPoolActiveOffer.objects.create(
            pool=pool, pool_offer=pool_offer, listing=listing,
            store_listing_id="pa-clone-2", pool_item=item,
            status=OfferPoolActiveOfferStatus.DELISTED,
        )
        order = self._order(store, owned, "PA-2")

        _record_sale_event(
            pool_offer, listing_id=listing.pk, event_key="pa:2",
            order_id=order.pk, active_offer=clone,
        )

        clone.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(clone.status, OfferPoolActiveOfferStatus.SOLD)
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)

    def test_append_sale_consumes_exact_item_by_owned_product(self):
        store = self._store("eldorado", "eldorado-store")
        pool, listing, pool_offer = self._pool(store, strategy=PoolOfferStrategy.APPEND)
        owned = self._owned("eld-acct")
        item = self._item(pool, pool_offer, owned)
        pool_offer.current_remote_count = 2
        pool_offer.save(update_fields=["current_remote_count"])
        order = self._order(store, owned, "ELD-1")

        _record_sale_event(
            pool_offer, listing_id=listing.pk, event_key="eld:1",
            order_id=order.pk, active_offer=None,
        )

        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)
        self.assertEqual(item.remote_state, "sold")

    def test_idempotent_second_event_does_not_error_or_flip(self):
        store = self._store("playerauctions", "pa-store3")
        pool, listing, pool_offer = self._pool(store, strategy=PoolOfferStrategy.CLONE)
        owned = self._owned("pa-acct3")
        item = self._item(pool, pool_offer, owned)
        clone = OfferPoolActiveOffer.objects.create(
            pool=pool, pool_offer=pool_offer, listing=listing,
            store_listing_id="pa-clone-3", pool_item=item,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        )
        order = self._order(store, owned, "PA-3")

        _record_sale_event(
            pool_offer, listing_id=listing.pk, event_key="pa:3",
            order_id=order.pk, active_offer=clone,
        )
        # Same event key again → deduped, no change.
        result = _record_sale_event(
            pool_offer, listing_id=listing.pk, event_key="pa:3",
            order_id=order.pk, active_offer=clone,
        )

        self.assertIsNone(result)
        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)
        self.assertEqual(PoolSaleEvent.objects.filter(pool_item=item).count(), 1)
