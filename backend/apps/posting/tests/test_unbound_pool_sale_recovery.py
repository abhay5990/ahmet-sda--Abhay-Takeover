from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

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
from apps.posting.services.pool.order_binding import (
    OrderBindingResult,
    recover_unbound_remote_removals,
)


class UnboundPoolSaleRecoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='recovery', title='Recovery')
        cls.game = Game.objects.create(
            name='Recovery Game', slug='recovery-game', category=cls.category,
        )
        cls.store = IntegrationAccount.objects.create(
            name='Recovery Eldorado', slug='recovery-eldorado',
            provider='eldorado', role='sell', is_active=True,
        )

    def _unbound_item(self, *, remote_state='absent'):
        pool = OfferPool.objects.create(
            name='Recovery Pool', game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        listing = Listing.objects.create(
            integration_account=self.store, game=self.game, is_instant=True,
            store_listing_id='recovery-offer', title='Recovery offer',
            status='listed', price=Decimal('10.00'), currency='USD',
        )
        lane = PoolOffer.objects.create(
            pool=pool, listing=listing, strategy=PoolOfferStrategy.APPEND,
            status=PoolOfferStatus.ACTIVE, target_count=1, threshold=1,
        )
        owned = OwnedProduct.objects.create(
            category=self.category, game=self.game, login='recovery-login',
            password='pw', status='draft',
        )
        return OfferPoolItem.objects.create(
            pool=pool, pool_offer=lane, owned_product=owned,
            status=OfferPoolItemStatus.CONSUMED, remote_state=remote_state,
        )

    def test_recovers_each_lane_once_and_never_reopens_stock(self):
        item = self._unbound_item()
        with patch(
            'apps.posting.services.pool.order_binding.refresh_and_bind_consumed_items',
            return_value=OrderBindingResult((item.pk,), ()),
        ) as refresh:
            summary = recover_unbound_remote_removals()

        self.assertEqual(summary['lanes_scanned'], 1)
        self.assertEqual(summary['bound_item_ids'], [item.pk])
        refresh.assert_called_once()
        self.assertEqual([candidate.pk for candidate in refresh.call_args.args[0]], [item.pk])
        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)

    def test_ignores_already_sold_remote_state(self):
        item = self._unbound_item(remote_state='sold')
        with patch(
            'apps.posting.services.pool.order_binding.refresh_and_bind_consumed_items',
        ) as refresh:
            summary = recover_unbound_remote_removals()

        self.assertEqual(summary['lanes_scanned'], 0)
        refresh.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)
