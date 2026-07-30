"""Reconciliation must not mark pushed items 'sold' on credential text drift.

Freshly-pushed pool items (e.g. posted via manual stock) can render different
credential text than the live offer after an account's fields are edited
(recovery email / email domain). Reconciliation must only consume items when
the remote credential COUNT actually drops (a real sale/removal), not on a
text mismatch while the offer still holds all credentials.
"""
from decimal import Decimal
from unittest.mock import patch

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
)
from apps.posting.services.pool.replenisher import (
    _PoolOfferContext,
    _reconcile_pushed_items,
)
from django.test import TestCase

_FMT = 'apps.posting.services.pool.replenisher.format_credential_for_marketplace'


class ReconcileNoFalseConsumeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="rc", title="RC")
        cls.game = Game.objects.create(name="Fortnite", slug="fortnite", category=cls.category)
        cls.store = IntegrationAccount.objects.create(
            name="Eldorado Mart", slug="eldorado-mart", provider="eldorado", role="sell",
        )

    def _offer_with_items(self, n):
        pool = OfferPool.objects.create(
            name="P", game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        listing = Listing.objects.create(
            is_instant=True, integration_account=self.store, game=self.game,
            store_listing_id="offer-1", status="listed", title="offer-1",
            price=Decimal("10.00"), currency="USD",
        )
        pool_offer = PoolOffer.objects.create(
            pool=pool, listing=listing, strategy=PoolOfferStrategy.APPEND,
            target_count=n, threshold=1, status=PoolOfferStatus.ACTIVE,
        )
        items = []
        for i in range(n):
            owned = OwnedProduct.objects.create(
                category=self.category, game=self.game,
                login=f"acct{i}", password="pw", status="listed",
            )
            items.append(OfferPoolItem.objects.create(
                pool=pool, pool_offer=pool_offer, owned_product=owned,
                status=OfferPoolItemStatus.PUSHED, remote_state="present", order=i,
            ))
        return pool, pool_offer, items

    def test_count_stable_text_mismatch_keeps_pushed(self):
        """Remote still holds all creds (count unchanged) → nothing consumed."""
        pool, pool_offer, items = self._offer_with_items(2)

        # Remote returns 2 credentials whose text does NOT match our render
        # (simulates field-edit / formatting drift). Count still equals pushed.
        with patch(_FMT, return_value="rendered-does-not-match"):
            consumed = _reconcile_pushed_items(
                _PoolOfferContext(pool_offer),
                ["remote-cred-A", "remote-cred-B"],
                remote_credential_ids={"idA", "idB"},
            )

        self.assertEqual(consumed, 0)
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.status, OfferPoolItemStatus.PUSHED)

    def test_real_count_drop_consumes_only_the_shortfall(self):
        """One credential actually sold (count 2→1) → exactly one consumed."""
        pool, pool_offer, items = self._offer_with_items(2)
        present, sold = items[0], items[1]

        def _fmt(owned, marketplace, pool=None):
            return "live-A" if owned.login == "acct0" else "live-B"

        # Remote now has only 'live-A' — acct1 ('live-B') is gone.
        with patch(_FMT, side_effect=_fmt):
            consumed = _reconcile_pushed_items(
                _PoolOfferContext(pool_offer),
                ["live-A"],
                remote_credential_ids=set(),
            )

        self.assertEqual(consumed, 1)
        present.refresh_from_db()
        sold.refresh_from_db()
        self.assertEqual(present.status, OfferPoolItemStatus.PUSHED)
        self.assertEqual(sold.status, OfferPoolItemStatus.CONSUMED)

    def test_all_gone_consumes_all(self):
        """Offer emptied (count → 0) → all pushed items consumed."""
        pool, pool_offer, items = self._offer_with_items(2)
        with patch(_FMT, return_value="whatever"):
            consumed = _reconcile_pushed_items(
                _PoolOfferContext(pool_offer),
                [],
                remote_credential_ids=set(),
            )
        self.assertEqual(consumed, 2)
