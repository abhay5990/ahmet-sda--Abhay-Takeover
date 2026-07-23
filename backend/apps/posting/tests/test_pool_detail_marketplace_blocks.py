from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from apps.posting.models import (
    OfferPoolActiveOfferStatus,
    OfferPoolItemStatus,
    PoolOfferStatus,
)
from apps.posting.views import _build_pool_marketplace_blocks


class PoolDetailMarketplaceBlocksTests(SimpleTestCase):
    def make_offer(
        self,
        *,
        offer_id,
        marketplace,
        store_name,
        status=PoolOfferStatus.ACTIVE,
    ):
        now = timezone.now()
        listing = SimpleNamespace(
            pk=offer_id + 100,
            store_listing_id=f'remote-{offer_id}',
            title=f'Listing {offer_id}',
        )
        return SimpleNamespace(
            pk=offer_id,
            marketplace=marketplace,
            store=SimpleNamespace(name=store_name),
            listing=listing,
            status=status,
            created_at=now,
            current_remote_count=2,
            threshold=1,
            target_count=3,
        )

    def make_item(self, *, item_id, status, pool_offer_id=None, login=None):
        now = timezone.now()
        return SimpleNamespace(
            pk=item_id,
            status=status,
            pool_offer_id=pool_offer_id,
            owned_product=SimpleNamespace(login=login or f'login-{item_id}'),
            consumed_at=now if status == OfferPoolItemStatus.CONSUMED else None,
            updated_at=now,
        )

    def test_builds_canonical_cards_with_shared_stock_and_exact_pa_order(self):
        eldorado = self.make_offer(
            offer_id=14,
            marketplace='eldorado',
            store_name='ezsmurfMart',
        )
        gameboost = self.make_offer(
            offer_id=16,
            marketplace='gameboost',
            store_name='EzSmurfMart',
        )
        playerauctions = self.make_offer(
            offer_id=18,
            marketplace='playerauctions',
            store_name='Csgosmurfkings',
        )
        consumed_eldorado_item = self.make_item(
            item_id=101,
            status=OfferPoolItemStatus.CONSUMED,
            pool_offer_id=eldorado.pk,
        )
        sold_pa_item = self.make_item(
            item_id=102,
            status=OfferPoolItemStatus.PUSHED,
            pool_offer_id=playerauctions.pk,
        )
        unallocated_item = self.make_item(
            item_id=103,
            status=OfferPoolItemStatus.PENDING,
        )
        pa_clone_listing_id = 501
        sold_pa_clone = SimpleNamespace(
            pool_offer_id=playerauctions.pk,
            pool_item_id=sold_pa_item.pk,
            listing_id=pa_clone_listing_id,
            store_listing_id='pa-clone-501',
            status=OfferPoolActiveOfferStatus.SOLD,
            updated_at=timezone.now(),
        )
        pa_sale = SimpleNamespace(
            pool_offer_id=playerauctions.pk,
            listing_id=pa_clone_listing_id,
            order_id=9001,
            created_at=timezone.now() - timedelta(minutes=1),
        )

        blocks, additional_blocks, unallocated = _build_pool_marketplace_blocks(
            [eldorado, gameboost, playerauctions],
            [consumed_eldorado_item, sold_pa_item, unallocated_item],
            [sold_pa_clone],
            [pa_sale],
        )

        self.assertEqual(
            [block['title'] for block in blocks],
            [
                'Eldorado Mart',
                'Eldorado Shop',
                'CsgoSmurfkings GameBoost',
                'GamerInstanty GameBoost',
                'CsgoSmurfkings PlayerAuctions',
                'Vapenation PlayerAuctions',
            ],
        )
        self.assertEqual(additional_blocks, [])
        self.assertEqual(unallocated, [unallocated_item])

        eldorado_block = blocks[0]
        self.assertIs(eldorado_block['primary_offer'], eldorado)
        self.assertEqual(eldorado_block['unallocated_pending_count'], 1)
        self.assertEqual(eldorado_block['sold_item_count'], 1)
        self.assertIsNone(eldorado_block['sold_items'][0]['order_id'])
        self.assertFalse(eldorado_block['sold_items'][0]['is_exact_order_match'])

        pa_block = blocks[4]
        self.assertIs(pa_block['primary_offer'], playerauctions)
        self.assertEqual(pa_block['sold_item_count'], 1)
        self.assertEqual(pa_block['sold_items'][0]['order_id'], 9001)
        self.assertTrue(pa_block['sold_items'][0]['is_exact_order_match'])
        self.assertEqual(pa_block['sale_history'][0], pa_sale)
