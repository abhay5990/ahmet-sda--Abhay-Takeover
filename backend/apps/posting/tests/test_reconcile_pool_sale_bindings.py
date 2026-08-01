"""Tests for the retroactive order<->pool-item binding command (Fix A)."""
from decimal import Decimal
from io import StringIO

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.orders.models import Order
from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
    PoolSaleEvent,
)
from django.core.management import call_command
from django.test import TestCase


class ReconcilePoolSaleBindingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="acc", title="Acc")
        cls.game = Game.objects.create(name="GTA V", slug="gtav", category=cls.category)
        cls.store = IntegrationAccount.objects.create(
            name="Eldorado Mart", slug="eldorado-mart", provider="eldorado", role="sell",
        )
        cls.pool = OfferPool.objects.create(
            name="P", game=cls.game, status=OfferPoolStatus.ACTIVE,
        )

    def _offer(self, store_listing_id="offer-1", store=None):
        listing = Listing.objects.create(
            is_instant=True, integration_account=store or self.store, game=self.game,
            store_listing_id=store_listing_id, status="listed", title=store_listing_id,
            price=Decimal("10"), currency="USD",
        )
        return PoolOffer.objects.create(
            pool=self.pool, listing=listing, strategy=PoolOfferStrategy.APPEND,
            target_count=5, threshold=2, status=PoolOfferStatus.ACTIVE,
        )

    def _consumed_item(self, offer, login):
        owned = OwnedProduct.objects.create(
            category=self.category, game=self.game, login=login, password="pw",
        )
        item = OfferPoolItem.objects.create(
            pool=self.pool, owned_product=owned, pool_offer=offer,
            status=OfferPoolItemStatus.CONSUMED,
        )
        return item, owned

    def _order(self, owned, store_order_id, store=None):
        return Order.objects.create(
            is_instant=True, integration_account=store or self.store,
            store_order_id=store_order_id, price=Decimal("10"), currency="USD",
            owned_product=owned,
        )

    def _run(self, **kw):
        out = StringIO()
        call_command("reconcile_pool_sale_bindings", stdout=out, stderr=StringIO(), **kw)
        return out.getvalue()

    def test_single_match_binds(self):
        offer = self._offer()
        item, owned = self._consumed_item(offer, "acct1")
        order = self._order(owned, "SO-1")

        self._run(apply=True)

        ev = PoolSaleEvent.objects.get(pool_item_id=item.pk)
        self.assertEqual(ev.order_id, order.pk)
        self.assertEqual(ev.pool_offer_id, offer.pk)
        self.assertEqual(ev.listing_id, offer.listing_id)
        self.assertEqual(ev.event_key, f"eldorado:{self.store.id}:SO-1:offer:{offer.pk}")

    def test_dry_run_writes_nothing(self):
        offer = self._offer()
        item, owned = self._consumed_item(offer, "acct2")
        self._order(owned, "SO-2")

        out = self._run()  # no --apply
        self.assertEqual(PoolSaleEvent.objects.count(), 0)
        self.assertIn("Would bind 1", out)

    def test_idempotent(self):
        offer = self._offer()
        item, owned = self._consumed_item(offer, "acct3")
        self._order(owned, "SO-3")

        self._run(apply=True)
        self._run(apply=True)
        self.assertEqual(PoolSaleEvent.objects.filter(pool_item_id=item.pk).count(), 1)

    def test_ambiguous_left_alone(self):
        offer = self._offer()
        item, owned = self._consumed_item(offer, "acct4")
        self._order(owned, "SO-4a")
        self._order(owned, "SO-4b")  # two orders for the same account+store

        self._run(apply=True)
        self.assertFalse(PoolSaleEvent.objects.filter(pool_item_id=item.pk).exists())

    def test_no_matching_order_left_alone(self):
        offer = self._offer()
        item, owned = self._consumed_item(offer, "acct5")
        # no order for this account

        self._run(apply=True)
        self.assertFalse(PoolSaleEvent.objects.filter(pool_item_id=item.pk).exists())

    def test_playerauctions_skipped(self):
        pa_store = IntegrationAccount.objects.create(
            name="PA", slug="pa-store", provider="playerauctions", role="sell",
        )
        offer = self._offer(store_listing_id="pa-offer-1", store=pa_store)
        item, owned = self._consumed_item(offer, "acct6")
        self._order(owned, "SO-6", store=pa_store)

        out = self._run(apply=True)
        self.assertFalse(PoolSaleEvent.objects.filter(pool_item_id=item.pk).exists())
        self.assertIn("skipped_pa 1", out)
