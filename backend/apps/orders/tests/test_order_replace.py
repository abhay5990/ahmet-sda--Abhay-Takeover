"""Tests for Order Replacement from the unallocated pool (spec v2, R1-R9)."""
from decimal import Decimal
from unittest.mock import patch

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, DropshipProduct, Game, OwnedProduct
from apps.orders.models import Order, OrderReplacement
from apps.posting.models import OfferPool, OfferPoolItem, OfferPoolItemStatus, OfferPoolStatus
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class OrderReplaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="staff", email="s@example.com", password="pw",
        )
        cls.category = Category.objects.create(name="accounts", title="Accounts")
        cls.game = Game.objects.create(name="GTA V", slug="gtav", category=cls.category)
        cls.pool = OfferPool.objects.create(
            name="GTA V PC", game=cls.game, status=OfferPoolStatus.ACTIVE,
        )

    def _owned(self, login, status="listed"):
        return OwnedProduct.objects.create(
            category=self.category, game=self.game, login=login,
            password=f"pw-{login}", email=f"{login}@mail.com",
            email_password="epw", ref_key=f"#{login[:6]}", status=status,
        )

    def _pool_item(self, owned, status=OfferPoolItemStatus.PENDING, order=0, **kw):
        return OfferPoolItem.objects.create(
            pool=self.pool, owned_product=owned, status=status, order=order, **kw,
        )

    def _order(self, owned=None, dropship=None, is_instant=False):
        return Order.objects.create(
            is_instant=is_instant, store_order_id=f"SO-{owned.login if owned else 'x'}",
            price=Decimal("10.00"), currency="USD",
            owned_product=owned, dropship_product=dropship,
        )

    def _post(self, order, reason="account banned", employee="Alice"):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("orders:api_replace", args=[order.id]),
            data={"reason": reason, "employee_name": employee},
        )

    def _emergency_post(self, order, old_item, reason="account faulty", employee="Alice"):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("orders:api_emergency_replace", args=[order.id]),
            data={
                "old_pool_item_id": old_item.id,
                "reason": reason,
                "employee_name": employee,
            },
        )

    # ── R2: happy path ────────────────────────────────────────────────
    def test_replace_swaps_from_unallocated_pool(self):
        old = self._owned("old1")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED, order=0)
        new1 = self._owned("new1")
        item1 = self._pool_item(new1, order=1)
        new2 = self._owned("new2")
        self._pool_item(new2, order=2)
        order = self._order(owned=old)

        resp = self._post(order)

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["credentials"]["login"], "new1")  # FIFO by id
        self.assertEqual(body["credentials"]["password"], "pw-new1")

        order.refresh_from_db()
        old.refresh_from_db()
        item1.refresh_from_db()
        self.assertEqual(order.owned_product_id, new1.id)
        self.assertEqual(old.status, "replaced")
        self.assertEqual(item1.status, OfferPoolItemStatus.REMOVED)
        self.assertIsNotNone(item1.consumed_at)

        rep = OrderReplacement.objects.get(order=order)
        self.assertEqual(rep.old_product_id, old.id)
        self.assertEqual(rep.new_product_id, new1.id)
        self.assertEqual(rep.employee_name, "Alice")
        self.assertEqual(rep.created_by_id, self.user.id)

    # ── R8: consumed unit is no longer dispatchable ───────────────────
    def test_consumed_unit_leaves_pending_pool(self):
        old = self._owned("old2")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        new = self._owned("newp")
        self._pool_item(new, order=1)
        order = self._order(owned=old)

        self.assertEqual(self.pool.pending_count, 1)
        self.assertEqual(self._post(order).status_code, 200)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.pending_count, 0)

    # ── R1: auto-sourced (dropship) order refused ─────────────────────
    def test_auto_sourced_order_rejected(self):
        ds = DropshipProduct.objects.create(
            source_product_id="lzt-1", price=Decimal("5"),
            product_title="x", category=self.category,
        )
        old = self._owned("old3")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        self._pool_item(self._owned("new3"), order=1)
        order = self._order(owned=old, dropship=ds)

        resp = self._post(order)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    # Manual entry is explicit: an instant owned account must not receive the
    # replacement workflow merely because it has no dropship-product link.
    def test_instant_owned_order_rejected(self):
        old = self._owned("instant1")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        self._pool_item(self._owned("instant-new"), order=1)
        order = self._order(owned=old, is_instant=True)

        resp = self._post(order)

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])
        self.assertIn("manual-entry", resp.json()["error"])

    # Legacy manual orders are self-owned even when the importer did not
    # persist their owned_product FK. They may open the replacement workflow;
    # execution remains safe and does not mutate anything until a stock-pool
    # link is available.
    def test_unlinked_manual_order_is_not_rejected_as_dropship(self):
        order = self._order(owned=None)

        resp = self._post(order)

        self.assertEqual(resp.status_code, 409)
        self.assertIn("no recorded stock-pool link", resp.json()["error"])
        self.assertEqual(OrderReplacement.objects.filter(order=order).count(), 0)

    def test_emergency_replace_explicitly_binds_confirmed_sold_pool_account(self):
        old = self._owned("emergency-old")
        old_item = self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        new = self._owned("emergency-new")
        new_item = self._pool_item(new, order=1)
        order = self._order(owned=None)
        order.status = "delivered"
        order.save(update_fields=["status"])

        response = self._emergency_post(order, old_item)

        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        old.refresh_from_db()
        old_item.refresh_from_db()
        new_item.refresh_from_db()
        replacement = OrderReplacement.objects.get(order=order)
        self.assertEqual(order.owned_product_id, new.id)
        self.assertEqual(replacement.old_product_id, old.id)
        self.assertEqual(replacement.new_product_id, new.id)
        self.assertEqual(old.status, "replaced")
        self.assertEqual(old_item.status, OfferPoolItemStatus.REMOVED)
        self.assertEqual(new_item.status, OfferPoolItemStatus.REMOVED)
        self.assertIn("Emergency sold-ledger binding", replacement.reason)

    def test_emergency_replace_allows_confirmed_instant_order_with_exact_sold_key(self):
        old = self._owned("emergency-instant-old")
        old_item = self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        new = self._owned("emergency-instant-new")
        self._pool_item(new, order=1)
        order = self._order(owned=None, is_instant=True)
        order.status = "delivered"
        order.save(update_fields=["status"])

        response = self._emergency_post(order, old_item)

        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.owned_product_id, new.id)

    def test_emergency_replace_rejects_pending_old_account(self):
        old = self._owned("emergency-pending-old")
        old_item = self._pool_item(old)
        self._pool_item(self._owned("emergency-pending-new"), order=1)
        order = self._order(owned=None)
        order.status = "delivered"
        order.save(update_fields=["status"])

        response = self._emergency_post(order, old_item)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(OrderReplacement.objects.filter(order=order).count(), 0)

    # ── R5: no unallocated stock ──────────────────────────────────────
    def test_no_unallocated_stock(self):
        old = self._owned("old4")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        order = self._order(owned=old)

        resp = self._post(order)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("No unallocated pool stock", resp.json()["error"])

    # ── R6: missing reason / employee ─────────────────────────────────
    def test_missing_reason_or_employee(self):
        old = self._owned("old5")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        self._pool_item(self._owned("new5"), order=1)
        order = self._order(owned=old)

        self.assertEqual(self._post(order, reason="", employee="Bob").status_code, 400)
        self.assertEqual(self._post(order, reason="ok reason", employee="").status_code, 400)
        # Nothing mutated by the replace view: order still points at old, the
        # product was not retired to 'replaced', and no audit row was written.
        order.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual(order.owned_product_id, old.id)
        self.assertNotEqual(old.status, "replaced")
        self.assertEqual(OrderReplacement.objects.filter(order=order).count(), 0)

    # ── R9: legacy stock not linked to a pool ─────────────────────────
    def test_order_product_not_in_pool(self):
        old = self._owned("old6")  # no pool item
        self._pool_item(self._owned("new6"), order=1)
        order = self._order(owned=old)

        resp = self._post(order)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("not linked to a stock pool", resp.json()["error"])

    # ── R7: replace twice → two audit rows ────────────────────────────
    def test_replace_twice_creates_two_audit_rows(self):
        old = self._owned("old7")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        self._pool_item(self._owned("new7a"), order=1)
        self._pool_item(self._owned("new7b"), order=2)
        order = self._order(owned=old)

        self.assertEqual(self._post(order).status_code, 200)
        self.assertEqual(self._post(order).status_code, 200)
        self.assertEqual(OrderReplacement.objects.filter(order=order).count(), 2)

    # ── skip units with a known failure ───────────────────────────────
    def test_failed_units_are_skipped(self):
        old = self._owned("old8")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        self._pool_item(self._owned("bad8"), order=1, error_message="login already exists")
        good = self._owned("good8")
        self._pool_item(good, order=2)
        order = self._order(owned=old)

        resp = self._post(order)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["credentials"]["login"], "good8")

    def test_visible_replace_button_only_for_confirmed_manual_pool_order(self):
        old = self._owned("visible-old")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        order = self._order(owned=old)
        order.status = "delivered"
        order.save(update_fields=["status"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("orders:list"))

        self.assertContains(response, "Replace")

    @patch("apps.orders.views.deliver_replacement")
    def test_replacement_returns_verified_delivery_status(self, deliver_replacement):
        deliver_replacement.return_value = {
            "status": "sent",
            "channel": "gameboost_chat",
            "message": "GameBoost customer message sent and confirmed by the provider.",
        }
        account = IntegrationAccount.objects.create(
            name="GB", slug="gb-replace", provider="gameboost",
        )
        old = self._owned("gb-old")
        self._pool_item(old, status=OfferPoolItemStatus.REMOVED)
        self._pool_item(self._owned("gb-new"), order=1)
        order = self._order(owned=old)
        order.integration_account = account
        order.save(update_fields=["integration_account"])

        response = self._post(order)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["delivery"]["status"], "sent")
        deliver_replacement.assert_called_once()
