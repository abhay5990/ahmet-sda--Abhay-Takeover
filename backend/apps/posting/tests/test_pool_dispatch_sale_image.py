from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.template.loader import get_template
from django.test import TestCase, override_settings

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolStatus,
    PostingImagePreset,
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
