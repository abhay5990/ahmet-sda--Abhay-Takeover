"""Exact-ID Mart renewal: eligible stock, verified expiry and durable outcomes."""
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.posting.models import (
    OfferPool, OfferPoolActiveOffer, OfferPoolActiveOfferStatus, OfferPoolItem, OfferPoolItemStatus,
    OfferPoolStatus, PoolOffer, PoolOfferStrategy,
)
from apps.sync.models import SyncFeatureFlag
from apps.sync.management.commands.renew_expiring_playerauctions import mart_renewal_request_id

CMD = 'apps.sync.management.commands.renew_expiring_playerauctions'


class RenewMartViaMctTests(TransactionTestCase):
    def setUp(self):
        SyncFeatureFlag.objects.update_or_create(key='sync.renew_expiring_playerauctions', defaults={'is_enabled': True})
        self.category = Category.objects.create(name='acc', title='Acc')
        self.game = Game.objects.create(name='GTA', slug='gta-test', category=self.category)
        self.mart = IntegrationAccount.objects.create(name='Mart', slug='playerauctions-csgosmurfkings', provider='playerauctions', role='sell')
        IntegrationCredential.objects.create(account=self.mart, credentials={'t': 'synthetic'})
        self.shop = IntegrationAccount.objects.create(name='Shop', slug='playerauctions-vapenation234', provider='playerauctions', role='sell')
        IntegrationCredential.objects.create(account=self.shop, credentials={'t': 'synthetic'})

    def listing(self, account, offer_id, days=2):
        return Listing.objects.create(
            is_instant=True, integration_account=account, game=self.game, store_listing_id=offer_id,
            status='listed', title='synthetic', price=Decimal('10'), currency='USD',
            marketplace_expires_at=timezone.now() + timedelta(days=days),
        )

    def pool_clone(self, listing):
        pool = OfferPool.objects.create(name='p', game=self.game, status=OfferPoolStatus.ACTIVE)
        po = PoolOffer.objects.create(pool=pool, listing=self.listing(self.mart, str(100000000 + pool.pk), days=40),
                                     strategy=PoolOfferStrategy.CLONE, target_count=1, threshold=1, max_concurrent=1)
        product = OwnedProduct.objects.create(category=self.category, game=self.game, status='listed', login=f'l{uuid.uuid4().hex[:6]}', password='synthetic')
        listing.listing_owned_products.create(owned_product=product)
        item = OfferPoolItem.objects.create(pool=pool, pool_offer=po, owned_product=product,
                                           status=OfferPoolItemStatus.PUSHED, target_offer_id=listing.store_listing_id)
        ao = OfferPoolActiveOffer.objects.create(pool=pool, pool_offer=po, listing=listing, pool_item=item,
                                                store_listing_id=listing.store_listing_id, status=OfferPoolActiveOfferStatus.ACTIVE)
        return ao, item

    def run_cmd(self, renew_result):
        client = Mock()
        client.uses_official_offer_api_only.return_value = True
        client.renew_offer.return_value = renew_result
        out = StringIO()
        with patch(f'{CMD}.registry.get_or_build_client', return_value=client):
            call_command('renew_expiring_playerauctions', '--execute', stdout=out)
        return client, out.getvalue()

    def success(self, offer_id):
        return SimpleNamespace(ok=True, data={'offer_id': offer_id, 'expires_at': (timezone.now()+timedelta(days=30)).isoformat()})

    def test_request_id_remains_stable_across_days(self):
        exp = timezone.now()
        rid = mart_renewal_request_id('299415947', exp, exp)
        self.assertEqual(rid, mart_renewal_request_id('299415947', exp, exp+timedelta(days=1)))
        self.assertNotEqual(rid, mart_renewal_request_id('299415947', exp+timedelta(seconds=1), exp))
        self.assertRegex(rid, r'^[A-Za-z0-9._:-]{12,128}$')

    def test_renewed_same_id_extends_verified_expiry(self):
        listing = self.listing(self.mart, '299415947')
        self.pool_clone(listing)
        client, out = self.run_cmd(self.success('299415947'))
        listing.refresh_from_db()
        self.assertIn('RENEWED', out)
        self.assertGreater(listing.marketplace_expires_at, timezone.now()+timedelta(days=29))
        client.renew_offer.assert_called_once()
        from apps.sync.models import PaMartRenewalAttempt
        self.assertEqual(PaMartRenewalAttempt.objects.get(listing=listing).status, 'succeeded')

    def test_replacement_id_moves_only_exact_listing_clone_and_key(self):
        listing = self.listing(self.mart, '299415947')
        ao, item = self.pool_clone(listing)
        self.run_cmd(self.success('299999999'))
        listing.refresh_from_db(); ao.refresh_from_db(); item.refresh_from_db()
        self.assertEqual(listing.store_listing_id, '299999999')
        self.assertEqual(ao.store_listing_id, '299999999')
        self.assertEqual(item.target_offer_id, '299999999')
        self.assertEqual(ao.status, OfferPoolActiveOfferStatus.ACTIVE)
        self.assertEqual(item.status, OfferPoolItemStatus.PUSHED)

    def test_external_rejection_does_not_claim_no_write_or_retry(self):
        listing = self.listing(self.mart, '299415947')
        self.pool_clone(listing)
        before = listing.marketplace_expires_at
        _, out = self.run_cmd(SimpleNamespace(ok=False, error=SimpleNamespace(details={'delegation_outcome': 'rejected', 'error_code': 'renew_daily_cap_reached'})))
        listing.refresh_from_db()
        self.assertIn('UNKNOWN', out)
        self.assertEqual(listing.marketplace_expires_at, before)

    def test_unknown_outcome_keeps_original_identity_and_expiry(self):
        listing = self.listing(self.mart, '299415947')
        self.pool_clone(listing)
        before = listing.marketplace_expires_at
        _, out = self.run_cmd(SimpleNamespace(ok=False, error=SimpleNamespace(details={'delegation_outcome': 'unknown'})))
        listing.refresh_from_db()
        self.assertIn('UNKNOWN', out)
        self.assertEqual(listing.store_listing_id, '299415947')
        self.assertEqual(listing.marketplace_expires_at, before)

    def test_shop_is_not_touched_by_default(self):
        self.listing(self.shop, '288000001')
        client, out = self.run_cmd(self.success('288000001'))
        client.renew_offer.assert_not_called()
        self.assertIn('candidates=0', out)

    def test_sale_evidence_blocks_renewal(self):
        from apps.orders.models import Order
        listing = self.listing(self.mart, '299415947')
        self.pool_clone(listing)
        Order.objects.create(integration_account=self.mart, store_listing_id='299415947', price=Decimal('10'))
        client, _ = self.run_cmd(self.success('299415947'))
        client.renew_offer.assert_not_called()

    def test_mart_client_without_exact_renewal_has_no_legacy_write_fallback(self):
        self.listing(self.mart, '299415947')
        client = SimpleNamespace(uses_official_offer_api_only=lambda: True, renew_offer=None)
        out = StringIO()
        with patch(f'{CMD}.registry.get_or_build_client', return_value=client), patch(f'{CMD}._renew_official_mart_account_offer') as legacy:
            call_command('renew_expiring_playerauctions', '--execute', stdout=out)
        legacy.assert_not_called()
        self.assertIn('exact-ID official renewal unavailable', out.getvalue())


class MctClientRenewTests(TestCase):
    def delegation_client(self):
        from apps.integrations.providers.playerauctions import MctMartDelegationClient
        client = MctMartDelegationClient.__new__(MctMartDelegationClient)
        client._url = 'https://invalid.example/api/sda/pa-mart/delegate'; client._token = 'synthetic'
        client._encrypted_envelope = lambda payload: {'v': 1}
        return client

    def test_renew_success_requires_offer_id_and_passes_expiry(self):
        client = self.delegation_client()
        expiry = (timezone.now()+timedelta(days=30)).isoformat()
        resp = Mock(status_code=200, content=b'1')
        resp.json.return_value = {'ok': True, 'status': 'succeeded', 'offerId': '299999999', 'expiresAt': expiry}
        with patch('apps.integrations.providers.playerauctions.requests.post', return_value=resp) as post:
            result = client.renew_offer('299415947', request_id='sda-renew-299415947-synthetic-cycle')
        self.assertTrue(result.ok)
        self.assertEqual(result.data['offer_id'], '299999999')
        self.assertEqual(result.data['expires_at'], expiry)
        self.assertEqual(post.call_args.kwargs['json']['requestId'], 'sda-renew-299415947-synthetic-cycle')
        self.assertEqual(post.call_args.kwargs['json']['action'], 'renew')

    def test_bad_offer_id_is_refused_locally(self):
        result = self.delegation_client().renew_offer('0123', request_id='sda-renew-synthetic-cycle')
        self.assertFalse(result.ok)
        self.assertEqual(result.error.details['delegation_outcome'], 'rejected')

    def test_missing_invalid_or_past_remote_expiry_is_unknown(self):
        for expiry in (None, '', 'not-a-date', '2020-01-01T00:00:00', '2020-01-01T00:00:00Z'):
            with self.subTest(expiry=expiry):
                resp = Mock(status_code=200, content=b'1')
                resp.json.return_value = {'ok': True, 'status': 'succeeded', 'offerId': '299999999', 'expiresAt': expiry}
                with patch('apps.integrations.providers.playerauctions.requests.post', return_value=resp):
                    result = self.delegation_client().renew_offer('299415947', request_id='sda-renew-synthetic-cycle')
                self.assertFalse(result.ok)
                self.assertEqual(result.error.details['delegation_outcome'], 'unknown')
                self.assertFalse(result.error.is_retryable)
