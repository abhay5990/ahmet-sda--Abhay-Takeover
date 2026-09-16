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
from apps.posting.api.stock import (
    _protected_pool_product_ids,
    _seed_pool_pending_items,
)
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

    def test_seeding_reuses_safely_removed_historical_account(self):
        """A fully detached unsold removed row must not block a fresh pool."""
        account = self._accounts(1)[0]
        old_pool = OfferPool.objects.create(
            name="Old", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        OfferPoolItem.objects.create(
            pool=old_pool,
            owned_product=account,
            live_owned_product=None,
            status=OfferPoolItemStatus.REMOVED,
            remote_state='absent',
        )

        pool = self._pool()
        _seed_pool_pending_items(pool, [account])

        new_item = OfferPoolItem.objects.get(pool=pool, owned_product=account)
        self.assertEqual(new_item.status, OfferPoolItemStatus.PENDING)
        self.assertEqual(new_item.live_owned_product_id, account.id)

    def test_seeding_keeps_removed_item_blocked_when_live_lock_remains(self):
        """Removed rows with retained remote or sale protection stay exclusive."""
        account = self._accounts(1)[0]
        old_pool = OfferPool.objects.create(
            name="Protected", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        OfferPoolItem.objects.create(
            pool=old_pool,
            owned_product=account,
            live_owned_product=account,
            status=OfferPoolItemStatus.REMOVED,
            remote_state='unknown',
        )

        pool = self._pool()
        _seed_pool_pending_items(pool, [account])

        self.assertFalse(
            OfferPoolItem.objects.filter(pool=pool, owned_product=account).exists()
        )

    def test_protected_owner_preflight_identifies_blocked_account(self):
        """A job must fail before posting when the new pool cannot own a key."""
        account = self._accounts(1)[0]
        old_pool = OfferPool.objects.create(
            name="Protected", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        OfferPoolItem.objects.create(
            pool=old_pool,
            owned_product=account,
            live_owned_product=account,
            status=OfferPoolItemStatus.REMOVED,
            remote_state='unknown',
        )

        self.assertSetEqual(_protected_pool_product_ids([account]), {account.id})

    def test_protected_owner_preflight_allows_safely_released_account(self):
        """A fully detached removed row remains reusable for stock posting."""
        account = self._accounts(1)[0]
        old_pool = OfferPool.objects.create(
            name="Released", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        OfferPoolItem.objects.create(
            pool=old_pool,
            owned_product=account,
            live_owned_product=None,
            status=OfferPoolItemStatus.REMOVED,
            remote_state='absent',
        )

        self.assertSetEqual(_protected_pool_product_ids([account]), set())

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

    def test_auto_link_reuses_same_listing_pool_offer_for_missing_account(self):
        """A retry may safely add an exact missing account to the same offer."""
        pool = self._pool()
        first, second = self._accounts(2)
        _seed_pool_pending_items(pool, [first, second])
        listing = self._listing()

        _auto_link_listing_to_pool(
            pool_id=pool.id,
            listing=listing,
            owned_products=[first],
            target_count=2,
            threshold=2,
            marketplace="eldorado",
        )
        _auto_link_listing_to_pool(
            pool_id=pool.id,
            listing=listing,
            owned_products=[second],
            target_count=2,
            threshold=2,
            marketplace="eldorado",
        )

        self.assertEqual(pool.pool_offers.count(), 1)
        self.assertEqual(
            OfferPoolItem.objects.filter(
                pool=pool,
                pool_offer__listing=listing,
                status=OfferPoolItemStatus.PUSHED,
            ).count(),
            2,
        )
