"""Tests for the read-only PA missed-sales diagnostic command."""
import json
import os
import tempfile
from decimal import Decimal

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
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
)
from django.core.management import call_command
from django.test import TestCase


class DiagnosePaPoolSalesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="acc", title="Acc")
        cls.game = Game.objects.create(
            name="GTA V", slug="grand-theft-auto-5", category=cls.category,
        )
        cls.store = IntegrationAccount.objects.create(
            name="PA", slug="playerauctions-csgo", provider="playerauctions", role="sell",
        )
        IntegrationCredential.objects.create(account=cls.store, credentials={"x": "y"})
        cls.pool = OfferPool.objects.create(
            name="GTA PA", game=cls.game, status=OfferPoolStatus.ACTIVE,
        )

    def _listing(self, sid):
        return Listing.objects.create(
            is_instant=True, integration_account=self.store, game=self.game,
            store_listing_id=sid, status="listed", title=sid,
            price=Decimal("10"), currency="USD",
        )

    def _run(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(os.remove, path)
        call_command("diagnose_pa_pool_sales", hours=48, json_path=path, stdout=None)
        with open(path) as fh:
            return json.load(fh)

    def test_reports_missed_order_clone_and_stale_item(self):
        pool_offer = PoolOffer.objects.create(
            pool=self.pool, listing=self._listing("po-1"),
            strategy=PoolOfferStrategy.CLONE, target_count=5, threshold=2, max_concurrent=5,
            status=PoolOfferStatus.ACTIVE,
        )
        owned = OwnedProduct.objects.create(
            category=self.category, game=self.game, login="gtaacct", password="pw",
        )
        item = OfferPoolItem.objects.create(
            pool=self.pool, owned_product=owned, pool_offer=pool_offer,
            status=OfferPoolItemStatus.PUSHED,
        )
        # A clone that is gone from the marketplace, with NO PoolSaleEvent.
        OfferPoolActiveOffer.objects.create(
            pool=self.pool, pool_offer=pool_offer, listing=self._listing("clone-1"),
            pool_item=item, store_listing_id="clone-1",
            status=OfferPoolActiveOfferStatus.DELISTED,
        )
        # A fetched PA GTA order with no pool sale binding.
        Order.objects.create(
            is_instant=True, integration_account=self.store, game=self.game,
            store_order_id="PA-ORDER-1", store_listing_id="clone-1",
            price=Decimal("10"), currency="USD",
        )

        report = self._run()

        self.assertEqual(len(report["orders_unbound"]), 1)
        self.assertEqual(report["orders_unbound"][0]["store_order_id"], "PA-ORDER-1")
        self.assertEqual(len(report["clones_missed"]), 1)
        self.assertEqual(report["clones_missed"][0]["store_listing_id"], "clone-1")
        self.assertEqual(report["stale_pushed_items"], [item.pk])

    def test_clean_pool_reports_nothing_missed(self):
        # An active, healthy clone with a fresh check → nothing flagged as missed.
        from django.utils import timezone
        pool_offer = PoolOffer.objects.create(
            pool=self.pool, listing=self._listing("po-2"),
            strategy=PoolOfferStrategy.CLONE, target_count=5, threshold=2, max_concurrent=5,
            status=PoolOfferStatus.ACTIVE, current_remote_count=5,
            last_checked_at=timezone.now(),
        )
        report = self._run()
        self.assertEqual(report["orders_unbound"], [])
        self.assertEqual(report["clones_missed"], [])
        self.assertEqual(report["stale_pushed_items"], [])
