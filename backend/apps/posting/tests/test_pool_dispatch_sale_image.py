from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import get_template
from django.test import TestCase, override_settings

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
    PostingImagePreset,
)
from apps.posting.services.pool.dispatcher import (
    PoolDispatchConflict,
    dispatch_offer_from_pool,
    reserve_pending_items_for_new_offer,
)


_TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='sda-pool-dispatch-media-')


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class PoolDispatchSaleImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='pool-sale-image-admin',
            password='test-password',
        )
        cls.category = Category.objects.create(
            name='pool-sale-image-accounts',
            title='Pool Sale Image Accounts',
        )
        cls.game = Game.objects.create(
            name='Pool Sale Image Game',
            slug='pool-sale-image-game',
            category=cls.category,
        )
        cls.store = IntegrationAccount.objects.create(
            name='Pool Sale Image Eldorado',
            slug='pool-sale-image-eldorado',
            provider='eldorado',
            role='sell',
        )
        IntegrationCredential.objects.create(
            account=cls.store,
            credentials={'test': 'credential'},
        )
        cls.mart_store = IntegrationAccount.objects.create(
            name='Pool Sale Image Mart',
            slug='playerauctions-csgosmurfkings',
            provider='playerauctions',
            role='sell',
        )
        IntegrationCredential.objects.create(
            account=cls.mart_store,
            credentials={'test': 'credential'},
        )
        cls.pool = OfferPool.objects.create(
            name='Pool Sale Image Test',
            game=cls.game,
            status=OfferPoolStatus.ACTIVE,
        )
        owned = OwnedProduct.objects.create(
            category=cls.category,
            game=cls.game,
            login='sale-image@example.test',
            password='secret',
        )
        OfferPoolItem.objects.create(pool=cls.pool, owned_product=owned)

        cls.preset = PostingImagePreset.objects.create(
            uploaded_by=cls.user,
            game=cls.game,
            name='Pre-fed GTA Image',
            sha256='a' * 64,
            mime_type='image/png',
            size_bytes=10,
            width=100,
            height=100,
        )
        cls.preset.image.save('prefed-test.png', ContentFile(b'image-data'), save=True)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = f'/posting/api/pools/{self.pool.pk}/dispatch-offer/'
        self.base_payload = {
            'store_id': self.store.pk,
            'count': 1,
            'target_count': 5,
            'threshold': 2,
            'max_concurrent': None,
            'sale_price': 44.95,
            'selected_image_preset_id': self.preset.pk,
            'batch_data': {
                'title': 'Direct Price Offer',
                'description': 'Uses a pre-fed image',
            },
            'store_settings': {
                'multiplier_low': '7.00',
                'multiplier_mid': '8.00',
                'multiplier_high': '9.00',
            },
        }

    def test_dispatch_requires_direct_sale_price(self):
        payload = dict(self.base_payload)
        payload.pop('sale_price')

        response = self.client.post(self.url, data=payload, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'sale_price must be greater than 0')

    def test_dispatch_requires_selected_prefed_image(self):
        payload = dict(self.base_payload)
        payload.pop('selected_image_preset_id')

        response = self.client.post(self.url, data=payload, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Please select or upload a listing image')

    @patch.dict(
        'apps.integrations.providers.playerauctions.os.environ',
        {'PA_MART_CREATE_HOLD': 'true'},
        clear=False,
    )
    @patch('apps.posting.services.pool.dispatcher.dispatch_offer_from_pool')
    def test_held_mart_dispatch_returns_before_job_or_reservation(self, dispatch_mock):
        payload = dict(self.base_payload)
        payload.update({
            'store_id': self.mart_store.pk,
            'target_count': 2,
            'threshold': 2,
            'max_concurrent': 2,
        })

        response = self.client.post(self.url, data=payload, content_type='application/json')

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['error_code'], 'mart_create_held')
        self.assertIn('No listing job or stock reservation was created.', response.json()['error'])
        dispatch_mock.assert_not_called()

    @patch.dict(
        'apps.integrations.providers.playerauctions.os.environ',
        {'PA_MART_CREATE_HOLD': 'false'},
        clear=False,
    )
    @patch('apps.posting.services.pool.dispatcher._launch_orchestrator')
    def test_mart_existing_lane_blocks_second_manual_target(self, launch_mock):
        listing = Listing.objects.create(
            is_instant=True,
            integration_account=self.mart_store,
            game=self.game,
            store_listing_id='existing-mart-offer',
            status='listed',
            title='Existing Mart lane',
            price='32.99',
            currency='USD',
        )
        PoolOffer.objects.create(
            pool=self.pool,
            listing=listing,
            strategy=PoolOfferStrategy.CLONE,
            target_count=2,
            threshold=2,
            max_concurrent=2,
            status=PoolOfferStatus.ACTIVE,
        )
        payload = dict(self.base_payload)
        payload.update({
            'store_id': self.mart_store.pk,
            'target_count': 2,
            'threshold': 2,
            'max_concurrent': 2,
        })

        response = self.client.post(self.url, data=payload, content_type='application/json')

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['error_code'], 'mart_pool_lane_conflict')
        self.assertIn('second lane is blocked', response.json()['error'])
        launch_mock.assert_not_called()

    @patch.dict(
        'apps.integrations.providers.playerauctions.os.environ',
        {'PA_MART_CREATE_HOLD': 'false'},
        clear=False,
    )
    def test_mart_active_reservation_blocks_concurrent_manual_dispatch(self):
        with transaction.atomic():
            first = reserve_pending_items_for_new_offer(
                pool=self.pool,
                store=self.mart_store,
                count=1,
            )
            with self.assertRaisesRegex(PoolDispatchConflict, 'already processing'):
                reserve_pending_items_for_new_offer(
                    pool=self.pool,
                    store=self.mart_store,
                    count=1,
                )

        self.assertEqual(first.status, 'active')
        self.assertEqual(first.items.count(), 1)

    @patch('apps.posting.services.pool.dispatcher._launch_orchestrator')
    def test_real_dispatch_resolves_marketplace_strategy(self, launch_mock):
        with self.captureOnCommitCallbacks(execute=True):
            job = dispatch_offer_from_pool(
                pool=self.pool,
                store=self.store,
                count=1,
                target_count=5,
                threshold=2,
                max_concurrent=None,
                batch_data=self.base_payload['batch_data'],
                store_settings=self.base_payload['store_settings'],
                media_settings={
                    'selected_image_preset_id': self.preset.pk,
                    'selected_image_path': self.preset.image.path,
                },
            )

        self.assertEqual(
            job.settings['_pool_dispatch']['strategy'],
            PoolOfferStrategy.APPEND,
        )
        launch_mock.assert_called_once_with(job.pk)

    @patch('apps.posting.services.pool.dispatcher.dispatch_offer_from_pool')
    def test_dispatch_normalizes_price_and_attaches_selected_image(self, dispatch_mock):
        dispatch_mock.return_value = SimpleNamespace(
            pk=321,
            total_count=1,
            settings={'_media': {'selected_image_preset_id': self.preset.pk}},
            pool_dispatch_reservation=None,
        )

        response = self.client.post(
            self.url,
            data=self.base_payload,
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201, response.content)
        kwargs = dispatch_mock.call_args.kwargs
        self.assertEqual(kwargs['batch_data']['price'], 44.95)
        self.assertEqual(kwargs['batch_data']['sales_price'], 44.95)
        self.assertEqual(kwargs['batch_data']['purchased_price'], 44.95)
        self.assertEqual(kwargs['store_settings']['multiplier_low'], '1.00')
        self.assertEqual(kwargs['store_settings']['multiplier_mid'], '1.00')
        self.assertEqual(kwargs['store_settings']['multiplier_high'], '1.00')
        self.assertEqual(kwargs['media_settings']['selected_image_preset_id'], self.preset.pk)
        self.assertTrue(
            kwargs['media_settings']['selected_image_path'].endswith(
                self.preset.image.name
            )
        )

    def test_create_offer_drawer_exposes_sale_price_and_image_controls(self):
        source = get_template('posting/restock_pool_detail.html').template.source

        self.assertIn('Sale Price (USD) *', source)
        self.assertIn('This is the final marketplace sale price. No multiplier is applied.', source)
        self.assertIn('Listing Image *', source)
        self.assertIn('/posting/api/image-presets/upload/', source)
        self.assertIn('selected_image_preset_id', source)
        self.assertNotIn('Low multiplier</label>', source)
        self.assertNotIn('Purchased $</label>', source)

    def test_create_offer_drawer_reenables_post_after_rejected_dispatch(self):
        source = get_template('posting/restock_pool_detail.html').template.source
        rejection_handler = """if (!resp.ok) {
                    this.dispatchDrawer.error = data.error || 'Dispatch failed.';
                    this.dispatchDrawer.submitting = false;
                    return;
                }"""
        self.assertIn(rejection_handler, source)

    def test_create_offer_drawer_waits_for_store_prefill_and_normalizes_pa_capacity(self):
        source = get_template('posting/restock_pool_detail.html').template.source

        self.assertIn(
            ':disabled="dispatchDrawer.loading || dispatchDrawer.submitting || dispatchDrawer.imageUploading"',
            source,
        )
        self.assertIn('this.syncPaCapacity();', source)
        self.assertIn('syncPaCapacity() {', source)
        self.assertIn('@input="syncPaCapacity()"', source)
        self.assertIn("'Max Concurrent cannot be lower than Target Count.'", source)
