from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apis_sdk.clients.marketplaces.eldorado.models import EldoradoOfferCredentialsResponse
from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.models import OfferPool, OfferPoolItem, OfferPoolItemStatus, PoolOffer
from apps.posting.services.pa_edit_queue import enqueue_pa_edit
from apps.posting.services import offer_editor


class FreshReadClient:
    def __init__(self, readable=True):
        self.readable = readable
        self.leased = False

    @contextmanager
    def offer_mutation(self, offer_id):
        self.leased = True
        try:
            yield True
        finally:
            self.leased = False

    def get_offer_account_details(self, *args, **kwargs):
        assert self.leased
        return SimpleNamespace(ok=self.readable, data=EldoradoOfferCredentialsResponse.model_validate({
            'accountsDetails': [{'id': 'credential-1', 'secretDetails': 'Login: fixture\nPassword: fixture-password'}]
        }) if self.readable else None)


class EldoradoEditPayloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='acc', title='Account')
        cls.game = Game.objects.create(name='Fortnite', slug='fortnite', category=cls.category)

    def _listing(self):
        store = IntegrationAccount.objects.create(name='Eldorado edit store', slug='eldorado-edit-store', provider='eldorado', role='sell')
        IntegrationCredential.objects.create(account=store, credentials={'test': 'x'})
        return Listing.objects.create(
            is_instant=True, integration_account=store, game=self.game,
            store_listing_id='eldorado-offer-1', status='listed', title='Old title',
            price=Decimal('20.00'), currency='USD', raw_data={
                'offerTitle': 'Old title', 'description': 'Old description',
                'pricePerUnit': {'amount': 20.0, 'currency': 'USD'}, 'quantity': 1,
                'gameId': '70', 'tradeEnvironmentValues': [], 'attributes': [],
                '_credential_entries': [{'id': 'credential-1', 'secretDetails': 'Login: stale-local\nPassword: stale-local-fixture'}],
            },
        )

    def _edit(self, listing, changes, client, provider):
        with patch.object(offer_editor, 'build_proxy_pool', return_value=None), \
             patch.object(offer_editor, 'get_group_name', return_value=''), \
             patch.object(offer_editor, 'get_or_build_client', return_value=client), \
             patch.object(offer_editor, 'get_provider', return_value=provider):
            return offer_editor.edit_offer(listing, changes)

    def test_eldorado_edit_uses_fresh_canonical_update_payload(self):
        listing = self._listing()
        captured = {}
        class Provider:
            def update_listing(self, client, external_id, payload):
                assert client.leased
                captured.update(external_id=external_id, payload=payload)
                return SimpleNamespace(ok=True, error=None)
        result = self._edit(listing, {'title': 'New title', 'description': 'New description', 'price': Decimal('31.50')}, FreshReadClient(), Provider())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(captured['external_id'], 'eldorado-offer-1')
        payload = captured['payload']
        self.assertEqual(payload['accountSecretDetails'], ['Login: fixture\nPassword: fixture-password'])
        self.assertEqual(payload['accountDeliveryDetails'][0]['accountDetails']['accountLogin'], 'fixture')
        self.assertEqual(payload['details']['offerTitle'], 'New title')
        self.assertEqual(payload['details']['description'], 'New description')
        self.assertEqual(payload['details']['pricing']['pricePerUnit']['amount'], 31.5)
        self.assertEqual(payload['details']['pricing']['minQuantity'], 1)
        self.assertEqual(payload['augmentedGame']['gameId'], '70')
        listing.refresh_from_db()
        self.assertEqual(listing.title, 'New title')

    def test_managed_stock_cannot_replace_an_unverified_remote_snapshot(self):
        listing = self._listing()
        product = OwnedProduct.objects.create(login='managed-fixture', password='fixture-password', password_hash='fixture-hash', category=self.category, game=self.game)
        ListingOwnedProduct.objects.create(listing=listing, owned_product=product)
        provider = SimpleNamespace(update_listing=lambda *args: self.fail('Unverified inventory must never be sent'))
        result = self._edit(listing, {'title': 'Must not apply'}, FreshReadClient(readable=False), provider)
        self.assertFalse(result.ok)
        listing.refresh_from_db()
        self.assertEqual(listing.title, 'Old title')
        self.assertEqual(listing.store_listing_id, 'eldorado-offer-1')

    def test_pool_pushed_item_cannot_bypass_fresh_read_requirement(self):
        listing = self._listing()
        pool = OfferPool.objects.create(game=self.game, store=listing.integration_account, strategy='append')
        pool_offer = PoolOffer.objects.create(pool=pool, listing=listing, strategy='append', target_count=1, threshold=1)
        product = OwnedProduct.objects.create(login='pool-fixture', password='fixture-password', password_hash='fixture-hash', category=self.category, game=self.game)
        OfferPoolItem.objects.create(pool=pool, pool_offer=pool_offer, owned_product=product, status=OfferPoolItemStatus.PUSHED)
        provider = SimpleNamespace(update_listing=lambda *args: self.fail('Stale local pool inventory must never be sent'))
        result = self._edit(listing, {'price': Decimal('22.00')}, FreshReadClient(readable=False), provider)
        self.assertFalse(result.ok)
        listing.refresh_from_db()
        self.assertEqual(listing.price, Decimal('20.00'))

    def test_pa_queue_persists_decimal_price_as_json_safe_value(self):
        listing = self._listing()
        request = enqueue_pa_edit(listing=listing, changes={'title': 'Queued title', 'description': 'Queued description', 'price': Decimal('34.90')})
        self.assertEqual(request.changes['price'], '34.90')
        self.assertEqual(request.changes['title'], 'Queued title')
        self.assertEqual(request.changes['description'], 'Queued description')

    def _assert_failed_update_preserves_offer(self, message):
        listing = self._listing()
        calls = []
        class Provider:
            def update_listing(self, client, external_id, payload):
                assert client.leased
                calls.append('update')
                return SimpleNamespace(ok=False, error=message)
            def create_listing(self, *args, **kwargs):
                raise AssertionError('A failed edit cannot create a replacement')
            def delete_listing(self, *args, **kwargs):
                raise AssertionError('A failed edit cannot delete the original')
        result = self._edit(listing, {'title': 'Must not apply', 'price': Decimal('24.00')}, FreshReadClient(), Provider())
        self.assertFalse(result.ok)
        self.assertEqual(calls, ['update'])
        listing.refresh_from_db()
        self.assertEqual(listing.status, 'listed')
        self.assertEqual(listing.store_listing_id, 'eldorado-offer-1')
        self.assertEqual(listing.title, 'Old title')
        self.assertEqual(listing.price, Decimal('20.00'))
        self.assertEqual(Listing.objects.count(), 1)

    def test_legacy_content_rejection_preserves_original_without_recreate(self):
        self._assert_failed_update_preserves_offer('Cannot update structured details on a legacy account entry')

    def test_instant_delivery_rejection_preserves_original_without_recreate(self):
        self._assert_failed_update_preserves_offer('HTTP 400: Instant delivery must contain account details.')
