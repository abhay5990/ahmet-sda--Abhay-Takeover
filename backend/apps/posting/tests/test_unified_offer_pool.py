from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.api.pool import _adopt_pa_source_listing
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PoolOfferStatus,
    PoolDispatchReservation,
    PoolOffer,
    PoolOfferStrategy,
    PoolSaleEvent,
)
from apps.posting.services.pool.allocation import (
    claim_pending_items,
    quarantine_stale_claims,
)
from apps.posting.services.pool.checker import notify_sale
from apps.posting.services.pool.lifecycle import detach_pool_offer
from apps.posting.services.pool.replenisher import (
    _ensure_pa_offer_description,
    replenish_pool_offer,
)


class UnifiedPoolTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name='test-accounts',
            title='Test Accounts',
        )
        cls.game = Game.objects.create(
            name='Test Game',
            slug='test-game',
            category=cls.category,
        )
        cls.eldorado = IntegrationAccount.objects.create(
            name='Eldorado Test',
            slug='eldorado-test',
            provider='eldorado',
            role='sell',
        )
        cls.playerauctions = IntegrationAccount.objects.create(
            name='PA Test',
            slug='pa-test',
            provider='playerauctions',
            role='sell',
        )
        IntegrationCredential.objects.create(
            account=cls.eldorado,
            credentials={'test': 'credential'},
        )
        IntegrationCredential.objects.create(
            account=cls.playerauctions,
            credentials={'test': 'credential'},
        )

    def make_pool(self, name='Pool'):
        return OfferPool.objects.create(
            name=name,
            game=self.game,
            status=OfferPoolStatus.ACTIVE,
        )

    def make_listing(self, account=None, remote_id='offer-1'):
        return Listing.objects.create(
            is_instant=True,
            integration_account=account or self.eldorado,
            game=self.game,
            store_listing_id=remote_id,
            status='listed',
            title=remote_id,
            price=Decimal('10.00'),
            currency='USD',
        )

    def make_owned(self, login):
        return OwnedProduct.objects.create(
            category=self.category,
            game=self.game,
            login=login,
            password='secret',
        )

    def make_pool_offer(self, pool, listing=None, **overrides):
        values = {
            'pool': pool,
            'listing': listing or self.make_listing(),
            'strategy': PoolOfferStrategy.APPEND,
            'target_count': 5,
            'threshold': 2,
            'max_concurrent': None,
        }
        values.update(overrides)
        return PoolOffer.objects.create(**values)

    def test_depleted_is_health_not_user_intent(self):
        pool = self.make_pool()
        self.make_pool_offer(pool)

        self.assertEqual(pool.status, OfferPoolStatus.ACTIVE)
        self.assertTrue(pool.is_depleted)
        self.assertEqual(pool.health, 'depleted')

    def test_owned_product_is_globally_exclusive(self):
        owned = self.make_owned('exclusive@example.test')
        first = self.make_pool('First')
        second = self.make_pool('Second')
        OfferPoolItem.objects.create(pool=first, owned_product=owned)

        with self.assertRaises(IntegrityError), transaction.atomic():
            OfferPoolItem.objects.create(pool=second, owned_product=owned)

    def test_claim_prevents_second_offer_from_taking_same_item(self):
        pool = self.make_pool()
        first_offer = self.make_pool_offer(pool)
        second_offer = self.make_pool_offer(
            pool,
            listing=self.make_listing(remote_id='offer-2'),
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=self.make_owned('claim@example.test'),
        )

        first_claim = claim_pending_items(first_offer, 1)
        second_claim = claim_pending_items(second_offer, 1)

        self.assertEqual([claimed.pk for claimed in first_claim], [item.pk])
        self.assertEqual(second_claim, [])
        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.QUEUED)
        self.assertEqual(item.pool_offer_id, first_offer.pk)
        self.assertIsNotNone(item.claim_token)
        self.assertEqual(item.dispatch_attempts.count(), 1)

    def test_stale_claim_is_quarantined_not_requeued(self):
        pool = self.make_pool()
        pool_offer = self.make_pool_offer(pool)
        item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=self.make_owned('stale@example.test'),
        )
        claim_pending_items(pool_offer, 1)
        OfferPoolItem.objects.filter(pk=item.pk).update(
            claimed_at=timezone.now() - timedelta(hours=1),
        )

        quarantined = quarantine_stale_claims(timedelta(minutes=15))

        item.refresh_from_db()
        self.assertEqual(quarantined, 1)
        self.assertEqual(item.status, OfferPoolItemStatus.FAILED)
        self.assertEqual(item.remote_state, 'unknown')
        self.assertEqual(item.pool_offer_id, pool_offer.pk)
        self.assertEqual(item.dispatch_attempts.get().status, 'unknown')

    def test_one_listing_cannot_be_linked_to_two_pools(self):
        listing = self.make_listing()
        self.make_pool_offer(self.make_pool('First'), listing=listing)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_pool_offer(self.make_pool('Second'), listing=listing)

    def test_sale_event_is_idempotent(self):
        pool = self.make_pool()
        pool_offer = self.make_pool_offer(pool)
        pool_offer.current_remote_count = 5
        pool_offer.save(update_fields=['current_remote_count', 'updated_at'])

        notify_sale(
            pool_offer.listing_id,
            event_key='eldorado:store:order-1',
            order_id=123,
        )
        notify_sale(
            pool_offer.listing_id,
            event_key='eldorado:store:order-1',
            order_id=123,
        )

        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.current_remote_count, 4)
        self.assertEqual(PoolSaleEvent.objects.count(), 1)

    def test_closed_pa_clone_keeps_replacement_lane_active(self):
        pool = self.make_pool()
        listing = self.make_listing(
            account=self.playerauctions,
            remote_id='pa-closed-clone',
        )
        pool_offer = self.make_pool_offer(
            pool,
            listing=listing,
            strategy=PoolOfferStrategy.CLONE,
            target_count=1,
            threshold=1,
            max_concurrent=1,
        )
        active_offer = OfferPoolActiveOffer.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            listing=listing,
            store_listing_id='pa-closed-clone',
            status=OfferPoolActiveOfferStatus.ACTIVE,
        )

        listing.status = 'closed'
        listing.save(update_fields=['status', 'updated_at'])

        pool_offer.refresh_from_db()
        active_offer.refresh_from_db()
        self.assertEqual(pool_offer.status, PoolOfferStatus.ACTIVE)
        self.assertEqual(pool_offer.last_error, '')
        self.assertEqual(active_offer.status, OfferPoolActiveOfferStatus.DELISTED)

    def test_verified_pa_order_recovers_delisted_clone_as_sold(self):
        pool = self.make_pool()
        listing = self.make_listing(
            account=self.playerauctions,
            remote_id='pa-delisted-clone',
        )
        pool_offer = self.make_pool_offer(
            pool,
            listing=listing,
            strategy=PoolOfferStrategy.CLONE,
            target_count=1,
            threshold=1,
            max_concurrent=1,
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=self.make_owned('pa-delayed-sale@example.test'),
            status=OfferPoolItemStatus.PUSHED,
            remote_state='absent',
        )
        active_offer = OfferPoolActiveOffer.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            listing=listing,
            pool_item=item,
            store_listing_id='pa-delisted-clone',
            status=OfferPoolActiveOfferStatus.DELISTED,
        )

        with patch(
            'apps.posting.services.pool.checker.replenish_pool_offer',
        ):
            notify_sale(
                listing.pk,
                event_key='playerauctions:pa-test:verified-delayed-order',
                order_id=91234,
            )

        active_offer.refresh_from_db()
        event = PoolSaleEvent.objects.get(
            event_key='playerauctions:pa-test:verified-delayed-order:active-offer:'
            f'{active_offer.pk}',
        )
        self.assertEqual(active_offer.status, OfferPoolActiveOfferStatus.SOLD)
        self.assertEqual(event.order_id, 91234)
        self.assertEqual(event.pool_item_id, item.pk)
        self.assertEqual(event.outcome, 'processed')

    def test_pa_replenish_rebuilds_from_stock_when_template_is_missing(self):
        pool = self.make_pool()
        listing = self.make_listing(
            account=self.playerauctions,
            remote_id='pa-legacy-source-without-template',
        )
        listing.raw_data = {}
        listing.save(update_fields=['raw_data', 'updated_at'])
        pool_offer = self.make_pool_offer(
            pool,
            listing=listing,
            strategy=PoolOfferStrategy.CLONE,
            target_count=1,
            threshold=1,
            max_concurrent=1,
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=self.make_owned('pa-stock-rebuild@example.test'),
        )

        with patch(
            'apps.posting.services.pool.replenisher.get_or_build_client',
            return_value=object(),
        ), patch(
            'apps.posting.services.pool.replenisher.extract_create_payload',
            return_value=None,
        ), patch(
            'apps.posting.services.pool.replenisher._rebuild_pa_offer_from_stock',
            return_value=1,
        ) as rebuild:
            pushed = replenish_pool_offer(pool_offer)

        self.assertEqual(pushed, 1)
        rebuild.assert_called_once()
        self.assertEqual(rebuild.call_args.args[2].pk, item.pk)
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.current_remote_count, 1)

    def test_pa_source_rebuild_supplies_description_only_when_blank(self):
        blank_payload = {'offerDesc': '   '}
        populated = _ensure_pa_offer_description(blank_payload)
        self.assertIn('Instant delivery.', populated['offerDesc'])
        self.assertTrue(populated['offerDesc'].strip())

        existing_payload = {'offerDesc': 'Existing product details.'}
        self.assertEqual(
            _ensure_pa_offer_description(existing_payload)['offerDesc'],
            'Existing product details.',
        )

    def test_pa_source_listing_is_adopted_as_first_active_offer(self):
        pool = self.make_pool()
        listing = self.make_listing(
            account=self.playerauctions,
            remote_id='pa-source-1',
        )
        owned = self.make_owned('pa-source@example.test')
        ListingOwnedProduct.objects.create(listing=listing, owned_product=owned)
        pool_offer = self.make_pool_offer(
            pool,
            listing=listing,
            strategy=PoolOfferStrategy.CLONE,
            target_count=5,
            threshold=2,
            max_concurrent=10,
        )

        _adopt_pa_source_listing(pool_offer)

        item = OfferPoolItem.objects.get(owned_product=owned)
        self.assertEqual(item.pool_offer_id, pool_offer.pk)
        self.assertEqual(item.status, OfferPoolItemStatus.PUSHED)
        self.assertTrue(
            OfferPoolActiveOffer.objects.filter(
                pool_offer=pool_offer,
                pool_item=item,
                listing=listing,
                status='active',
            ).exists()
        )
        pool_offer.refresh_from_db()
        self.assertEqual(pool_offer.current_remote_count, 1)

    def test_api_creates_independent_pool_then_links_offer(self):
        user = get_user_model().objects.create_user(
            username='pool-admin',
            password='test-password',
        )
        self.client.force_login(user)
        listing = self.make_listing(remote_id='api-offer')

        create_response = self.client.post(
            '/posting/api/pools/',
            data={
                'name': 'API Unified Pool',
                'game_id': self.game.pk,
            },
            content_type='application/json',
        )
        self.assertEqual(create_response.status_code, 201)
        pool_id = create_response.json()['pool']['id']
        pool = OfferPool.objects.get(pk=pool_id)
        self.assertIsNone(pool.listing_id)
        self.assertEqual(pool.pool_offers.count(), 0)

        link_response = self.client.post(
            f'/posting/api/pools/{pool_id}/offers/',
            data={
                'listing_id': listing.pk,
                'target_count': 5,
                'threshold': 2,
                'max_concurrent': 10,  # ignored for append providers
            },
            content_type='application/json',
        )
        self.assertEqual(link_response.status_code, 201, link_response.content)
        linked = PoolOffer.objects.get(pool=pool)
        self.assertEqual(linked.listing_id, listing.pk)
        self.assertEqual(linked.strategy, PoolOfferStrategy.APPEND)
        self.assertIsNone(linked.max_concurrent)

    def test_pool_api_rename_trims_name_and_rejects_blank(self):
        user = get_user_model().objects.create_user(
            username='pool-rename-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Original Pool Name')

        rename_response = self.client.patch(
            f'/posting/api/pools/{pool.pk}/update/',
            data={'name': '  Renamed Pool  '},
            content_type='application/json',
        )

        self.assertEqual(rename_response.status_code, 200, rename_response.content)
        self.assertEqual(rename_response.json()['pool']['name'], 'Renamed Pool')
        pool.refresh_from_db()
        self.assertEqual(pool.name, 'Renamed Pool')

        blank_response = self.client.patch(
            f'/posting/api/pools/{pool.pk}/update/',
            data={'name': '   '},
            content_type='application/json',
        )

        self.assertEqual(blank_response.status_code, 400)
        self.assertEqual(blank_response.json()['error'], 'name cannot be empty')
        pool.refresh_from_db()
        self.assertEqual(pool.name, 'Renamed Pool')

    def test_pool_list_allows_safe_history_and_blocks_active_marketplace_work(self):
        user = get_user_model().objects.create_user(
            username='pool-delete-eligibility-user',
            password='test-password',
        )
        self.client.force_login(user)
        empty_pool = self.make_pool('Empty Pool')
        pool_with_history = self.make_pool('Pool With Removed Item')
        OfferPoolItem.objects.create(
            pool=pool_with_history,
            owned_product=self.make_owned('removed-history@example.test'),
            status=OfferPoolItemStatus.REMOVED,
        )
        pool_with_pending_item = self.make_pool('Pool With Pending Item')
        OfferPoolItem.objects.create(
            pool=pool_with_pending_item,
            owned_product=self.make_owned('pending-delete@example.test'),
            status=OfferPoolItemStatus.PENDING,
        )
        pool_with_active_offer = self.make_pool('Pool With Active Offer')
        self.make_pool_offer(pool_with_active_offer)

        response = self.client.get('/posting/api/pools/')

        self.assertEqual(response.status_code, 200)
        pools = {entry['id']: entry for entry in response.json()['pools']}
        self.assertTrue(pools[empty_pool.pk]['can_hard_delete'])
        self.assertEqual(pools[pool_with_history.pk]['items_total'], 0)
        self.assertTrue(pools[pool_with_history.pk]['can_hard_delete'])
        self.assertTrue(pools[pool_with_pending_item.pk]['can_hard_delete'])
        self.assertFalse(pools[pool_with_active_offer.pk]['can_hard_delete'])
        self.assertIn(
            'active_linked_offers',
            pools[pool_with_active_offer.pk]['delete_blockers'],
        )

    def test_hard_delete_cleans_pool_history_but_preserves_listing_and_inventory(self):
        user = get_user_model().objects.create_user(
            username='pool-delete-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Disposable Historical Pool')
        listing = self.make_listing(remote_id='preserved-offer')
        owned = self.make_owned('preserved-inventory@example.test')
        listing_link = ListingOwnedProduct.objects.create(
            listing=listing,
            owned_product=owned,
        )
        pool_offer = self.make_pool_offer(
            pool,
            listing=listing,
            status='detached',
        )
        OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=owned,
            status=OfferPoolItemStatus.CONSUMED,
        )
        sale_event = PoolSaleEvent.objects.create(
            event_key='pool-delete:sale-history',
            listing=listing,
            pool_offer=pool_offer,
        )

        response = self.client.post(
            f'/posting/api/pools/{pool.pk}/delete/',
            data={'hard': True},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['deleted'])
        self.assertEqual(response.json()['removed_pool_items'], 1)
        self.assertEqual(response.json()['removed_pool_offers'], 1)
        self.assertFalse(OfferPool.objects.filter(pk=pool.pk).exists())
        self.assertFalse(PoolOffer.objects.filter(pk=pool_offer.pk).exists())
        self.assertTrue(OwnedProduct.objects.filter(pk=owned.pk).exists())
        self.assertTrue(Listing.objects.filter(pk=listing.pk).exists())
        self.assertTrue(ListingOwnedProduct.objects.filter(pk=listing_link.pk).exists())
        sale_event.refresh_from_db()
        self.assertIsNone(sale_event.pool_offer_id)

    def test_hard_delete_rejects_active_offer_items_and_dispatch_reservations(self):
        user = get_user_model().objects.create_user(
            username='pool-delete-blocker-user',
            password='test-password',
        )
        self.client.force_login(user)
        active_pool = self.make_pool('Active Marketplace Pool')
        active_offer = self.make_pool_offer(active_pool)
        OfferPoolItem.objects.create(
            pool=active_pool,
            pool_offer=active_offer,
            owned_product=self.make_owned('active-delete-guard@example.test'),
            status=OfferPoolItemStatus.PUSHED,
            remote_state='present',
        )
        reserved_pool = self.make_pool('Reserved Pool')
        PoolDispatchReservation.objects.create(
            pool=reserved_pool,
            store=self.eldorado,
            status='active',
            item_count=0,
        )

        active_response = self.client.post(
            f'/posting/api/pools/{active_pool.pk}/delete/',
            data={'hard': True},
            content_type='application/json',
        )
        reserved_response = self.client.post(
            f'/posting/api/pools/{reserved_pool.pk}/delete/',
            data={'hard': True},
            content_type='application/json',
        )

        self.assertEqual(active_response.status_code, 409)
        self.assertEqual(active_response.json()['error_code'], 'pool_delete_blocked')
        self.assertIn('active_pool_items', active_response.json()['blockers'])
        self.assertIn('active_linked_offers', active_response.json()['blockers'])
        self.assertEqual(reserved_response.status_code, 409)
        self.assertIn(
            'active_dispatch_reservations',
            reserved_response.json()['blockers'],
        )
        self.assertTrue(OfferPool.objects.filter(pk=active_pool.pk).exists())
        self.assertTrue(OfferPool.objects.filter(pk=reserved_pool.pk).exists())

    def test_pool_list_template_explains_safe_delete_cleanup(self):
        user = get_user_model().objects.create_user(
            username='pool-delete-template-user',
            password='test-password',
        )
        self.client.force_login(user)

        response = self.client.get('/posting/restock/pools/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'listings and inventory accounts are preserved')
        self.assertContains(response, 'pool.delete_blockers')
        self.assertContains(response, 'The pool and its local pool history will be removed')

    def test_leave_remote_detach_preserves_assignment(self):
        user = get_user_model().objects.create_user(
            username='pool-operator',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool()
        pool_offer = self.make_pool_offer(pool)
        item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=self.make_owned('detached@example.test'),
            status=OfferPoolItemStatus.PUSHED,
            remote_state='present',
        )

        response = self.client.post(
            f'/posting/api/pools/{pool.pk}/offers/{pool_offer.pk}/unlink/',
            data={'mode': 'leave_remote'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        pool_offer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(pool_offer.status, 'detached')
        self.assertEqual(item.status, OfferPoolItemStatus.PUSHED)
        self.assertEqual(item.pool_offer_id, pool_offer.pk)

    def test_remove_remote_releases_only_after_provider_success(self):
        pool = self.make_pool()
        pool_offer = self.make_pool_offer(pool)
        owned = self.make_owned('cleanup@example.test')
        item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=owned,
            status=OfferPoolItemStatus.PUSHED,
            remote_state='present',
            target_offer_id=pool_offer.listing.store_listing_id,
        )
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=owned,
        )

        with patch(
            'apps.posting.services.pool.lifecycle._remove_eldorado',
            side_effect=lambda _offer, items: ({entry.pk for entry in items}, []),
        ):
            result = detach_pool_offer(pool_offer, 'remove_remote')

        self.assertTrue(result.ok)
        self.assertEqual(result.released, 1)
        pool_offer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(pool_offer.status, 'detached')
        self.assertEqual(item.status, OfferPoolItemStatus.PENDING)
        self.assertIsNone(item.pool_offer_id)
        self.assertEqual(item.remote_state, 'absent')
        self.assertEqual(item.dispatch_attempts.get().status, 'succeeded')

    def test_restock_pages_render_with_unified_relations(self):
        user = get_user_model().objects.create_user(
            username='pool-page-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Rendered Pool')
        self.make_pool_offer(pool)

        list_response = self.client.get('/posting/restock/pools/')
        detail_response = self.client.get(f'/posting/restock/pools/{pool.pk}/')

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(list_response, 'Edit Name')
        self.assertContains(list_response, 'savePoolName(pool)')
        self.assertContains(list_response, 'Delete is temporarily blocked')
        self.assertContains(detail_response, 'Rendered Pool')
        self.assertContains(detail_response, 'Linked Offers')

    def test_pool_detail_removes_pending_key_but_keeps_account_inventory(self):
        user = get_user_model().objects.create_user(
            username='pool-pending-remove-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Pending Key Removal Pool')
        product = self.make_owned('pending-pool-key')
        item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=product,
            status=OfferPoolItemStatus.PENDING,
        )

        response = self.client.post(
            f'/posting/api/pools/{pool.pk}/items/{item.pk}/remove/',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['removed_from_marketplace'])
        self.assertFalse(OfferPoolItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(OwnedProduct.objects.filter(pk=product.pk).exists())

    def test_pool_detail_removes_assigned_key_from_marketplace_and_pool(self):
        user = get_user_model().objects.create_user(
            username='pool-assigned-remove-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Assigned Key Removal Pool')
        pool_offer = self.make_pool_offer(pool, threshold=2, target_count=5)
        pool_offer.current_remote_count = 3
        pool_offer.save(update_fields=['current_remote_count'])
        product = self.make_owned('assigned-pool-key')
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=product,
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=product,
            status=OfferPoolItemStatus.PUSHED,
            remote_state='present',
        )

        with patch(
            'apps.posting.services.pool.lifecycle._remove_eldorado',
            return_value=({item.pk}, []),
        ):
            response = self.client.post(
                f'/posting/api/pools/{pool.pk}/items/{item.pk}/remove/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['removed_from_marketplace'])
        self.assertFalse(ListingOwnedProduct.objects.filter(
            listing=pool_offer.listing,
            owned_product=product,
        ).exists())
        item.refresh_from_db()
        pool_offer.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.REMOVED)
        self.assertEqual(item.remote_state, 'absent')
        self.assertEqual(pool_offer.current_remote_count, 2)
        self.assertTrue(OwnedProduct.objects.filter(pk=product.pk).exists())

    def test_pool_detail_blocks_removal_while_key_is_reserved(self):
        user = get_user_model().objects.create_user(
            username='pool-reserved-remove-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Reserved Key Removal Pool')
        product = self.make_owned('reserved-pool-key')
        reservation = PoolDispatchReservation.objects.create(
            pool=pool,
            store=self.eldorado,
            item_count=1,
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=product,
            reservation=reservation,
            status=OfferPoolItemStatus.RESERVED,
        )

        response = self.client.post(
            f'/posting/api/pools/{pool.pk}/items/{item.pk}/remove/',
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('in-progress dispatch', response.json()['error'])
        self.assertTrue(OfferPoolItem.objects.filter(pk=item.pk).exists())

    def test_pool_detail_exposes_individual_pending_and_assigned_key_actions(self):
        user = get_user_model().objects.create_user(
            username='pool-key-actions-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Individual Key Actions Pool')
        pool_offer = self.make_pool_offer(pool)
        pending_item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=self.make_owned('pending-key-action'),
            status=OfferPoolItemStatus.PENDING,
        )
        assigned_product = self.make_owned('assigned-key-action')
        assigned_item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=assigned_product,
            status=OfferPoolItemStatus.PUSHED,
            remote_state='present',
        )
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=assigned_product,
        )
        consumed_product = self.make_owned('consumed-key-action')
        consumed_item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=consumed_product,
            status=OfferPoolItemStatus.CONSUMED,
            remote_state='absent',
        )
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=consumed_product,
        )
        reservation = PoolDispatchReservation.objects.create(
            pool=pool,
            store=self.eldorado,
            item_count=1,
        )
        reserved_item = OfferPoolItem.objects.create(
            pool=pool,
            owned_product=self.make_owned('reserved-key-action'),
            reservation=reservation,
            status=OfferPoolItemStatus.RESERVED,
        )

        response = self.client.get(f'/posting/restock/pools/{pool.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Remove from Pool')
        self.assertContains(response, 'Delete Key')
        self.assertContains(response, 'Delete this individual key from the Pool?')
        self.assertContains(
            response,
            f'removeLinkedKey({pool_offer.listing_id}, {consumed_product.pk}',
        )
        self.assertContains(
            response,
            f"removeItem({pool.pk}, {pending_item.pk}, 'pending', false",
        )
        self.assertContains(
            response,
            f"removeItem({pool.pk}, {assigned_item.pk}, 'pushed', true",
        )
        self.assertContains(
            response,
            f"removeItem({pool.pk}, {consumed_item.pk}, 'consumed', true",
        )
        self.assertNotContains(
            response,
            f"removeItem({pool.pk}, {reserved_item.pk}, 'reserved'",
        )
        self.assertContains(response, 'In progress')

    def test_listing_remove_key_removes_remote_credential_then_marks_item_removed(self):
        user = get_user_model().objects.create_user(
            username='remove-key-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Remove One Key Pool')
        pool_offer = self.make_pool_offer(pool, threshold=2, target_count=5)
        pool_offer.current_remote_count = 3
        pool_offer.save(update_fields=['current_remote_count'])
        product = self.make_owned('remove-one-key')
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=product,
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=product,
            status=OfferPoolItemStatus.PUSHED,
            remote_state='present',
        )

        with patch(
            'apps.posting.services.pool.lifecycle._remove_eldorado',
            return_value=({item.pk}, []),
        ):
            response = self.client.post(
                f'/listings/api/{pool_offer.listing_id}/keys/{product.pk}/remove/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['remote_removed'])
        self.assertFalse(ListingOwnedProduct.objects.filter(
            listing=pool_offer.listing,
            owned_product=product,
        ).exists())
        item.refresh_from_db()
        pool_offer.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.REMOVED)
        self.assertEqual(item.remote_state, 'absent')
        self.assertEqual(pool_offer.current_remote_count, 2)
        self.assertEqual(item.dispatch_attempts.get().status, 'succeeded')

    def test_listing_remove_key_unlinks_consumed_history_without_remote_call(self):
        user = get_user_model().objects.create_user(
            username='remove-history-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Remove Historical Key Pool')
        pool_offer = self.make_pool_offer(pool)
        pool_offer.listing.status = 'deleted'
        pool_offer.listing.save(update_fields=['status'])
        product = self.make_owned('remove-history-key')
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=product,
        )
        item = OfferPoolItem.objects.create(
            pool=pool,
            pool_offer=pool_offer,
            owned_product=product,
            status=OfferPoolItemStatus.CONSUMED,
            remote_state='absent',
        )

        with patch('apps.posting.services.pool.lifecycle._remove_eldorado') as remove:
            response = self.client.post(
                f'/listings/api/{pool_offer.listing_id}/keys/{product.pk}/remove/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['remote_removed'])
        remove.assert_not_called()
        self.assertFalse(ListingOwnedProduct.objects.filter(
            listing=pool_offer.listing,
            owned_product=product,
        ).exists())
        item.refresh_from_db()
        self.assertEqual(item.status, OfferPoolItemStatus.CONSUMED)
        self.assertTrue(OwnedProduct.objects.filter(pk=product.pk).exists())

    def test_listing_remove_key_blocks_active_unmanaged_listing(self):
        user = get_user_model().objects.create_user(
            username='remove-unmanaged-user',
            password='test-password',
        )
        self.client.force_login(user)
        product = self.make_owned('unmanaged-key')
        listing = Listing.objects.create(
            game=self.game,
            integration_account=self.eldorado,
            store_listing_id='unmanaged-live-offer',
            title='Unmanaged live offer',
            price=Decimal('10.00'),
            status='listed',
            is_instant=True,
        )
        ListingOwnedProduct.objects.create(
            listing=listing,
            owned_product=product,
        )

        response = self.client.post(
            f'/listings/api/{listing.pk}/keys/{product.pk}/remove/',
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('not managed by an Auto-Restock Pool', response.json()['error'])
        self.assertTrue(ListingOwnedProduct.objects.filter(
            listing=listing,
            owned_product=product,
        ).exists())

    def test_listing_detail_exposes_delete_key_and_store_specific_threshold_copy(self):
        user = get_user_model().objects.create_user(
            username='listing-key-ui-user',
            password='test-password',
        )
        self.client.force_login(user)
        pool = self.make_pool('Store Threshold Pool')
        pool_offer = self.make_pool_offer(pool, threshold=3, target_count=7)
        product = self.make_owned('listing-key-ui')
        ListingOwnedProduct.objects.create(
            listing=pool_offer.listing,
            owned_product=product,
        )

        response = self.client.get(f'/listings/{pool_offer.listing_id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Key')
        self.assertContains(response, 'This Store Threshold / Target')
        self.assertContains(response, 'These settings apply only to this listing/store.')
        self.assertContains(response, self.eldorado.name)
