"""Auto-recovery of append lanes parked in ERROR by a local listing-close event.

When a non-PA (Eldorado/GameBoost) source Listing is observed CLOSED/DELETED,
``listing_deactivated`` marks the attached PoolOffer ERROR with
``last_error="Listing status changed to closed"``. That fails ``can_replenish``,
so the scheduled sweep records the remote count but never re-adds keys, even
when the shared pool still has stock (pool-30 failure report).

The automatic sweep must recover such a lane — but ONLY once the remote offer
state is verified, never on an inconclusive result, so a local deactivation is
never mistaken for a genuine remote disappearance.
"""
from decimal import Decimal

from django.test import TestCase

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, Game
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import (
    OfferPool,
    OfferPoolStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
)
from apps.posting.services.pool.checker import (
    _OFFER_NOT_FOUND,
    _maybe_recover_errored_append_lane,
)


class ErroredLaneRecoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="rc", title="RC")
        cls.game = Game.objects.create(
            name="GTA", slug="grand-theft-auto-5", category=cls.category,
        )
        cls.store = IntegrationAccount.objects.create(
            name="Eldorado Mart", slug="eldorado-mart", provider="eldorado", role="sell",
        )

    def _errored_lane(
        self,
        *,
        marketplace="eldorado",
        provider="eldorado",
        strategy=PoolOfferStrategy.APPEND,
        last_error="Listing status changed to closed",
        offer_status=PoolOfferStatus.ERROR,
        pool_status=OfferPoolStatus.ACTIVE,
        listing_status=ListingStatus.CLOSED,
    ):
        store = self.store
        if provider != "eldorado":
            store = IntegrationAccount.objects.create(
                name=f"{provider}-store", slug=f"{provider}-store",
                provider=provider, role="sell",
            )
        pool = OfferPool.objects.create(name="P", game=self.game, status=pool_status)
        listing = Listing.objects.create(
            is_instant=True, integration_account=store, game=self.game,
            store_listing_id="offer-1", status=listing_status, title="offer-1",
            price=Decimal("10.00"), currency="USD",
        )
        pool_offer = PoolOffer.objects.create(
            pool=pool, listing=listing, strategy=strategy,
            target_count=2, threshold=1, status=offer_status,
            last_error=last_error,
            max_concurrent=5 if strategy == PoolOfferStrategy.CLONE else None,
        )
        return pool_offer, listing

    def test_verified_absent_reactivates_lane(self):
        pool_offer, listing = self._errored_lane()

        recovered = _maybe_recover_errored_append_lane(pool_offer, _OFFER_NOT_FOUND)

        self.assertTrue(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ACTIVE)
        self.assertEqual(pool_offer.last_error, "")
        # A verified-absent offer is recreated by the missing-offer path, so the
        # stale local listing is left for that path (not force-relisted here).
        listing.refresh_from_db()
        self.assertEqual(listing.status, ListingStatus.CLOSED)

    def test_verified_present_reactivates_and_relists(self):
        pool_offer, listing = self._errored_lane()

        recovered = _maybe_recover_errored_append_lane(pool_offer, 3)

        self.assertTrue(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ACTIVE)
        self.assertEqual(pool_offer.last_error, "")
        # The offer still exists remotely → the local CLOSED was wrong; correct
        # it so the close signal cannot immediately re-block the lane.
        listing.refresh_from_db()
        self.assertEqual(listing.status, ListingStatus.LISTED)

    def test_inconclusive_remote_does_not_recover(self):
        pool_offer, listing = self._errored_lane()

        recovered = _maybe_recover_errored_append_lane(pool_offer, None)

        self.assertFalse(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ERROR)
        self.assertEqual(pool_offer.last_error, "Listing status changed to closed")

    def test_gameboost_present_reactivates(self):
        pool_offer, listing = self._errored_lane(
            marketplace="gameboost", provider="gameboost",
        )

        recovered = _maybe_recover_errored_append_lane(pool_offer, 0)

        self.assertTrue(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ACTIVE)

    def test_unrelated_error_is_not_recovered(self):
        pool_offer, _ = self._errored_lane(
            last_error="Remote key removal failed (500)",
        )
        recovered = _maybe_recover_errored_append_lane(pool_offer, _OFFER_NOT_FOUND)
        self.assertFalse(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ERROR)

    def test_pa_clone_lane_is_not_recovered(self):
        pool_offer, _ = self._errored_lane(
            provider="playerauctions", strategy=PoolOfferStrategy.CLONE,
        )
        recovered = _maybe_recover_errored_append_lane(pool_offer, _OFFER_NOT_FOUND)
        self.assertFalse(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ERROR)

    def test_paused_pool_is_not_recovered(self):
        pool_offer, _ = self._errored_lane(pool_status=OfferPoolStatus.PAUSED)
        recovered = _maybe_recover_errored_append_lane(pool_offer, 3)
        self.assertFalse(recovered)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ERROR)
