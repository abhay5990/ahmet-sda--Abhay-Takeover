from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.posting.models import (
    ManualFaultyPoolTransfer,
    OfferPool,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PoolDispatchAttempt,
    PoolDispatchOperation,
    PoolDispatchStatus,
    PoolOffer,
    PoolOfferStrategy,
    PoolSaleEvent,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class ManualFaultyPoolTransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="fault-staff", email="fault-staff@example.test", password="pw",
        )
        cls.category = Category.objects.create(name="fault-tests", title="Fault tests")
        cls.game = Game.objects.create(
            name="Fault test game", slug="fault-test-game", category=cls.category,
        )
        cls.pool = OfferPool.objects.create(
            name="Fault pool", game=cls.game, status=OfferPoolStatus.ACTIVE,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _owned(self, login):
        return OwnedProduct.objects.create(
            category=self.category,
            game=self.game,
            login=login,
            password="stored-secret",
        )

    def _linked_item(self, *, login="history-account", status=OfferPoolItemStatus.PUSHED):
        owned = self._owned(login)
        listing = Listing.objects.create(
            is_instant=True,
            game=self.game,
            store_listing_id=f"offer-{login}",
            status="listed",
            title=f"Listing {login}",
            price=Decimal("10.00"),
        )
        offer = PoolOffer.objects.create(
            pool=self.pool,
            listing=listing,
            strategy=PoolOfferStrategy.APPEND,
            target_count=2,
            threshold=1,
        )
        item = OfferPoolItem.objects.create(
            pool=self.pool,
            pool_offer=offer,
            owned_product=owned,
            status=status,
            target_offer_id=f"remote-{login}",
            remote_state="present",
        )
        return item, offer, listing

    def _move(self, item, reason="Credentials no longer valid"):
        return self.client.post(
            reverse("posting:api_move_pool_item_to_faulty", args=[self.pool.id, item.id]),
            data={"reason": reason},
            content_type="application/json",
        )

    def test_manual_transfer_accepts_historical_marketplace_evidence_and_keeps_it(self):
        item, offer, listing = self._linked_item()
        PoolSaleEvent.objects.create(
            event_key="manual-fault-history-event",
            listing=listing,
            pool_offer=offer,
            pool_item=item,
            outcome="historical",
        )

        response = self._move(item)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["ok"])
        item.refresh_from_db()
        transfer = ManualFaultyPoolTransfer.objects.get(pool_item=item)
        self.assertEqual(item.status, OfferPoolItemStatus.REMOVED)
        self.assertEqual(item.pool_offer_id, offer.id)
        self.assertEqual(item.target_offer_id, "remote-history-account")
        self.assertEqual(item.remote_state, "present")
        self.assertEqual(item.live_owned_product_id, item.owned_product_id)
        self.assertEqual(transfer.reason, "Credentials no longer valid")
        self.assertEqual(transfer.created_by_id, self.user.id)

        # The terminal row holds its live owner lock, so an account moved to
        # Faulty cannot silently become stock in a different pool.
        other_pool = OfferPool.objects.create(
            name="Other fault pool", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfferPoolItem.objects.create(
                    pool=other_pool,
                    owned_product=item.owned_product,
                    status=OfferPoolItemStatus.PENDING,
                )

        page = self.client.get(
            reverse("posting:restock_pool_detail", args=[self.pool.id]),
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context["manual_faulty_transfers"]), 1)
        self.assertEqual(page.context["faulty_count"], 1)

    def test_manual_transfer_refuses_an_in_progress_dispatch(self):
        item, offer, _ = self._linked_item(
            login="in-flight-account", status=OfferPoolItemStatus.FAILED,
        )
        PoolDispatchAttempt.objects.create(
            item=item,
            pool_offer=offer,
            operation=PoolDispatchOperation.REMOVE,
            status=PoolDispatchStatus.IN_PROGRESS,
            request_fingerprint="a" * 64,
        )

        response = self._move(item)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("being dispatched", response.json()["error"])
        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.FAILED)
        self.assertFalse(ManualFaultyPoolTransfer.objects.filter(pool_item=item).exists())

    def test_manual_transfer_requires_a_reason(self):
        item, _, _ = self._linked_item(login="reason-required")

        response = self._move(item, reason="no")

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(ManualFaultyPoolTransfer.objects.filter(pool_item=item).exists())

    def test_pool_detail_template_includes_manual_faulty_control(self):
        source = get_template("posting/restock_pool_detail.html").template.source

        self.assertIn("Move to Faulty", source)
        self.assertIn("moveItemToFaulty", source)
        self.assertIn("Manual staff holds", source)
