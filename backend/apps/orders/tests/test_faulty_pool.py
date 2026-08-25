"""Fix C — faulty pool: a replaced account is retired to a terminal state,
never re-offered, and surfaced in the pool's Faulty section."""
from decimal import Decimal

from apps.inventory.models import Category, Game, OwnedProduct
from apps.inventory.enums import OwnedProductStatus
from apps.orders.models import FaultyAccountReturn, Order, OrderReplacement
from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
)
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class FaultyPoolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="staff", email="s@example.com", password="pw",
        )
        cls.category = Category.objects.create(name="accounts", title="Accounts")
        cls.game = Game.objects.create(name="GTA V", slug="gtav", category=cls.category)
        cls.pool = OfferPool.objects.create(
            name="P", game=cls.game, status=OfferPoolStatus.ACTIVE,
        )

    def _owned(self, login):
        return OwnedProduct.objects.create(
            category=self.category, game=self.game, login=login,
            password=f"pw-{login}", email=f"{login}@m.com", ref_key=f"#{login[:6]}",
        )

    def _item(self, owned, status=OfferPoolItemStatus.PENDING, order=0):
        return OfferPoolItem.objects.create(
            pool=self.pool, owned_product=owned, status=status, order=order,
        )

    def _order(self, owned):
        # Manual-entry classification (is_instant=False) is required for Replace.
        return Order.objects.create(
            is_instant=False, store_order_id=f"SO-{owned.login}",
            price=Decimal("10"), currency="USD", owned_product=owned,
        )

    def _replace(self, order, reason="account banned", employee="Alice"):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("orders:api_replace", args=[order.id]),
            data={"reason": reason, "employee_name": employee},
        )

    def test_old_item_retired_to_terminal_faulty_state(self):
        old = self._owned("faulty1")
        old_item = self._item(old, status=OfferPoolItemStatus.FAILED)  # sold/problematic
        self._item(self._owned("good1"), order=1)
        order = self._order(old)

        self.assertEqual(self._replace(order).status_code, 200)

        old_item.refresh_from_db()
        self.assertEqual(old_item.status, OfferPoolItemStatus.REMOVED)
        self.assertIn("faulty", old_item.error_message.lower())

    def test_replacement_recorded_for_pool_faulty_section(self):
        old = self._owned("faulty2")
        self._item(old, status=OfferPoolItemStatus.FAILED)
        self._item(self._owned("good2"), order=1)
        order = self._order(old)

        self._replace(order)

        # This is exactly the query the pool-detail view uses for the Faulty section.
        rows = OrderReplacement.objects.filter(pool_item__pool=self.pool)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().old_product.login, "faulty2")

    def test_faulty_account_never_reoffered(self):
        old = self._owned("faulty3")
        self._item(old, status=OfferPoolItemStatus.PENDING)  # even if left pending
        self._item(self._owned("good3"), order=1)
        order = self._order(old)

        self.assertEqual(self._replace(order).status_code, 200)  # consumes good3
        # No unallocated stock remains (good3 removed, old3 now faulty/removed).
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.pending_count, 0)
        # A second attempt cannot hand out the faulty account.
        resp = self._replace(order)
        self.assertEqual(resp.status_code, 409)

    def test_pool_detail_page_shows_faulty_count(self):
        old = self._owned("faulty4")
        self._item(old, status=OfferPoolItemStatus.FAILED)
        self._item(self._owned("good4"), order=1)
        order = self._order(old)
        self._replace(order)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("posting:restock_pool_detail", args=[self.pool.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["faulty_count"], 1)

    def test_fixed_faulty_account_can_return_to_pending_common_stock(self):
        old = self._owned("fixed-faulty")
        old_item = self._item(old, status=OfferPoolItemStatus.FAILED)
        self._item(self._owned("replacement-good"), order=1)
        order = self._order(old)
        self.assertEqual(self._replace(order).status_code, 200)
        replacement = OrderReplacement.objects.get(order=order)

        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "posting:api_return_faulty_to_common_stock",
                args=[self.pool.id, replacement.id],
            ),
            data='{"reason":"Credentials repaired and tested","employee_name":"Alice"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        old_item.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual(old_item.status, OfferPoolItemStatus.PENDING)
        self.assertEqual(old.status, OwnedProductStatus.RECOVERED)
        self.assertTrue(FaultyAccountReturn.objects.filter(replacement=replacement).exists())
