"""Tests for seeding all job accounts into the pool as unallocated stock.

Covers the fix where a stock-start job that creates a pool must place every
created account into the pool: the posted subset is promoted to PUSHED/linked,
while the surplus stays PENDING/unallocated (shared pool stock) instead of
vanishing.
"""
from decimal import Decimal

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.posting.api.stock import _seed_pool_pending_items
from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
)
from apps.posting.services.shared.listing_writer import _auto_link_listing_to_pool
from django.test import TestCase


class SeedUnallocatedStockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="seed", title="Seed")
        cls.game = Game.objects.create(name="Fortnite", slug="fortnite", category=cls.category)
        cls.store = IntegrationAccount.objects.create(
            name="Eldorado Mart", slug="eldorado-mart", provider="eldorado", role="sell",
        )

    def _pool(self):
        return OfferPool.objects.create(
            name="Job Pool", game=self.game, status=OfferPoolStatus.ACTIVE,
        )

    def _accounts(self, n):
        return [
            OwnedProduct.objects.create(
                category=self.category, game=self.game,
                login=f"acct{i:03d}", password="pw",
            )
            for i in range(n)
        ]

    def _listing(self):
        return Listing.objects.create(
            is_instant=True, integration_account=self.store, game=self.game,
            store_listing_id="offer-xyz", status="listed", title="offer-xyz",
            price=Decimal("10.00"), currency="USD",
        )

    def test_seeding_adds_all_as_pending_unallocated(self):
        pool = self._pool()
        accounts = self._accounts(30)
        _seed_pool_pending_items(pool, accounts)

        self.assertEqual(pool.items.count(), 30)
        self.assertEqual(
            OfferPoolItem.objects.filter(
                pool=pool,
                status=OfferPoolItemStatus.PENDING,
                pool_offer__isnull=True,
                reservation__isnull=True,
            ).count(),
            30,
        )
        pool.refresh_from_db()
        self.assertEqual(pool.pending_count, 30)

    def test_seeding_is_idempotent(self):
        pool = self._pool()
        accounts = self._accounts(5)
        _seed_pool_pending_items(pool, accounts)
        _seed_pool_pending_items(pool, accounts)
        self.assertEqual(pool.items.count(), 5)

    def test_seeding_skips_accounts_already_in_another_pool(self):
        """An account already in another pool is skipped, never crashing seeding."""
        accounts = self._accounts(3)
        other_pool = OfferPool.objects.create(
            name="Other", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        OfferPoolItem.objects.create(
            pool=other_pool, owned_product=accounts[0],
            status=OfferPoolItemStatus.PENDING,
        )

        pool = self._pool()
        _seed_pool_pending_items(pool, accounts)  # must not raise

        self.assertEqual(pool.items.count(), 2)
        self.assertFalse(
            OfferPoolItem.objects.filter(pool=pool, owned_product=accounts[0]).exists()
        )

    def test_posted_subset_promoted_surplus_stays_unallocated(self):
        """After seeding 30 and posting 2, exactly 2 are PUSHED and 28 stay shared."""
        pool = self._pool()
        accounts = self._accounts(30)
        _seed_pool_pending_items(pool, accounts)

        posted = accounts[:2]
        listing = self._listing()
        _auto_link_listing_to_pool(
            pool_id=pool.id,
            listing=listing,
            owned_products=posted,
            target_count=2,
            threshold=2,
            marketplace="eldorado",
        )

        # No duplicates created — still exactly 30 items in the pool.
        self.assertEqual(pool.items.count(), 30)

        pushed = OfferPoolItem.objects.filter(
            pool=pool, status=OfferPoolItemStatus.PUSHED, pool_offer__isnull=False,
        )
        self.assertEqual(pushed.count(), 2)
        self.assertSetEqual(
            {it.owned_product_id for it in pushed},
            {a.id for a in posted},
        )

        # The other 28 remain unallocated shared stock.
        pool.refresh_from_db()
        self.assertEqual(pool.pending_count, 28)
