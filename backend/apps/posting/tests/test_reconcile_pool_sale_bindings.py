"""Retroactively bind verified orders to pool items sold via reconciliation.

A pool item consumed by the remote-count sweep (or a direct PA sale that did not
match by listing) is left CONSUMED with no PoolSaleEvent, so the pool "sold" page
shows "Remote reconciliation — waiting for a verified marketplace order sync"
with no order id. The command must attach the real order via the account's
OwnedProduct so the verified order id renders.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.orders.enums import OrderStatus
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
from apps.posting.services.pool.order_binding import (
    bind_consumed_items_to_confirmed_orders,
)


class ReconcilePoolSaleBindingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="rc", title="RC")
        cls.game = Game.objects.create(
            name="GTA", slug="grand-theft-auto-5", category=cls.category,
        )
        cls.store = IntegrationAccount.objects.create(
            name="PA CsgoSmurf", slug="playerauctions-csgosmurfkings",
            provider="playerauctions", role="sell",
        )

    def _pool_with_consumed_item(self, login, *, consumed=True):
        pool = OfferPool.objects.create(
            name="P", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        listing = Listing.objects.create(
            is_instant=True, integration_account=self.store, game=self.game,
            store_listing_id=f"offer-{login}", status="listed", title=f"offer-{login}",
            price=Decimal("10.00"), currency="USD",
        )
        pool_offer = PoolOffer.objects.create(
            pool=pool, listing=listing, strategy=PoolOfferStrategy.APPEND,
            target_count=2, threshold=1, status=PoolOfferStatus.ACTIVE,
        )
        owned = OwnedProduct.objects.create(
            category=self.category, game=self.game,
            login=login, password="pw", status="sold",
        )
        item = OfferPoolItem.objects.create(
            pool=pool, pool_offer=pool_offer, owned_product=owned,
            status=(
                OfferPoolItemStatus.CONSUMED if consumed
                else OfferPoolItemStatus.PUSHED
            ),
            remote_state="absent" if consumed else "present", order=0,
            consumed_at=timezone.now() if consumed else None,
        )
        return pool, pool_offer, owned, item

    def _order(self, owned, *, store_order_id, status=OrderStatus.COMPLETED):
        return Order.objects.create(
            integration_account=self.store,
            store_order_id=store_order_id,
            owned_product=owned,
            status=status,
            price=Decimal("20.00"),
            currency="USD",
            sold_at=timezone.now(),
        )

    def test_binds_consumed_item_to_order_by_owned_product(self):
        pool, pool_offer, owned, item = self._pool_with_consumed_item("linenezot")
        order = self._order(owned, store_order_id="PA-16364033")

        out = StringIO()
        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), "--apply", stdout=out)

        event = PoolSaleEvent.objects.get(pool_item=item)
        self.assertEqual(event.order_id, order.pk)
        self.assertEqual(event.pool_offer_id, pool_offer.pk)
        self.assertEqual(event.outcome, "processed")

    def test_dry_run_does_not_persist(self):
        pool, _po, owned, item = self._pool_with_consumed_item("azugubeebutor")
        self._order(owned, store_order_id="PA-1")

        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), stdout=StringIO())

        self.assertFalse(PoolSaleEvent.objects.filter(pool_item=item).exists())

    def test_idempotent(self):
        pool, _po, owned, item = self._pool_with_consumed_item("rahedumihedini")
        self._order(owned, store_order_id="PA-2")

        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), "--apply", stdout=StringIO())
        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), "--apply", stdout=StringIO())

        self.assertEqual(PoolSaleEvent.objects.filter(pool_item=item).count(), 1)

    def test_reports_when_no_local_order_exists(self):
        pool, _po, _owned, item = self._pool_with_consumed_item("noorderaccount")

        out = StringIO()
        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), "--apply", stdout=out)

        self.assertFalse(PoolSaleEvent.objects.filter(pool_item=item).exists())
        self.assertIn("NO local order", out.getvalue())

    def test_skips_cancelled_order(self):
        pool, _po, owned, item = self._pool_with_consumed_item("cancelledacct")
        self._order(owned, store_order_id="PA-CX", status=OrderStatus.CANCELLED)

        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), "--apply", stdout=StringIO())

        self.assertFalse(PoolSaleEvent.objects.filter(pool_item=item).exists())

    def test_fills_orderless_existing_event(self):
        pool, pool_offer, owned, item = self._pool_with_consumed_item("orderless")
        order = self._order(owned, store_order_id="PA-FILL")
        # An event exists but was recorded without an order id.
        PoolSaleEvent.objects.create(
            event_key="legacy-orderless",
            listing=pool_offer.listing,
            pool_offer=pool_offer,
            pool_item=item,
            order_id=None,
            outcome="processing",
        )

        call_command("reconcile_pool_sale_bindings", "--pool", str(pool.pk), "--apply", stdout=StringIO())

        event = PoolSaleEvent.objects.get(pool_item=item)
        self.assertEqual(event.order_id, order.pk)

    def test_first_pass_binder_creates_exact_confirmed_sale_event(self):
        _pool, _pool_offer, owned, item = self._pool_with_consumed_item('first-pass')
        order = self._order(owned, store_order_id='PA-FIRST', status=OrderStatus.COMPLETED)

        result = bind_consumed_items_to_confirmed_orders([item])

        self.assertEqual(result.bound_item_ids, (item.pk,))
        event = PoolSaleEvent.objects.get(pool_item=item)
        self.assertEqual(event.order_id, order.pk)
        item.refresh_from_db()
        self.assertEqual(item.remote_state, 'sold')

    def test_first_pass_binder_rejects_pending_order(self):
        _pool, _pool_offer, owned, item = self._pool_with_consumed_item('pending-first-pass')
        self._order(owned, store_order_id='PA-PENDING', status=OrderStatus.PENDING)

        result = bind_consumed_items_to_confirmed_orders([item])

        self.assertEqual(result.bound_item_ids, ())
        self.assertFalse(PoolSaleEvent.objects.filter(pool_item=item).exists())
