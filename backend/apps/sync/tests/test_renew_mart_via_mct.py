"""Mart pre-expiry renewal through MCT's exact-ID renew action (4 Nov 2026)."""
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing
from apps.posting.models import (
    OfferPool, OfferPoolActiveOffer, OfferPoolActiveOfferStatus, OfferPoolItem, OfferPoolItemStatus,
    OfferPoolStatus, PoolOffer, PoolOfferStrategy,
)
from apps.sync.management.commands.renew_expiring_playerauctions import mart_renewal_request_id

CMD = 'apps.sync.management.commands.renew_expiring_playerauctions'


class RenewMartViaMctTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='acc', title='Acc')
        self.game = Game.objects.create(name='GTA', slug='gta-test', category=self.category)
        self.mart = IntegrationAccount.objects.create(name='Mart', slug='playerauctions-csgosmurfkings', provider='playerauctions', role='sell')
        IntegrationCredential.objects.create(account=self.mart, credentials={'t': 'c'})
        self.shop = IntegrationAccount.objects.create(name='Shop', slug='playerauctions-vapenation234', provider='playerauctions', role='sell')
        IntegrationCredential.objects.create(account=self.shop, credentials={'t': 'c'})

    def listing(self, account, offer_id, days=2):
        return Listing.objects.create(
            is_instant=True, integration_account=account, game=self.game, store_listing_id=offer_id,
            status='listed', title='t', price=Decimal('10'), currency='USD',
            marketplace_expires_at=timezone.now() + timedelta(days=days),
        )

    def pool_clone(self, listing):
        pool = OfferPool.objects.create(name='p', game=self.game, status=OfferPoolStatus.ACTIVE)
        po = PoolOffer.objects.create(pool=pool, listing=self.listing(self.mart, '100', days=40),
                                      strategy=PoolOfferStrategy.CLONE, target_count=1, threshold=1, max_concurrent=1)
        product = OwnedProduct.objects.create(category=self.category, game=self.game, login=f'l{uuid.uuid4().hex[:6]}', password='p')
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

    def test_request_id_is_deterministic_per_offer_expiry_and_day(self):
        exp = timezone.now()
        rid = mart_renewal_request_id('299415947', exp, exp)
        self.assertEqual(rid, mart_renewal_request_id('299415947', exp, exp))
        self.assertRegex(rid, r'^[A-Za-z0-9._:-]{12,128}$')  # MCT safeRequestId

    def test_renewed_same_id_extends_expiry(self):
        listing = self.listing(self.mart, '299415947')
        exp = (timezone.now() + timedelta(days=30)).isoformat()
        client, out = self.run_cmd(SimpleNamespace(ok=True, data={'offer_id': '299415947', 'expires_at': exp}))
        listing.refresh_from_db()
        self.assertIn('RENEWED', out)
        self.assertGreater(listing.marketplace_expires_at, timezone.now() + timedelta(days=29))
        self.assertEqual(listing.raw_data['official_renewal']['previous_offer_id'], '299415947')
        self.assertTrue(client.renew_offer.call_args.kwargs['request_id'].startswith('sda-renew-299415947-'))

    def test_replacement_id_moves_listing_clone_and_key_together(self):
        listing = self.listing(self.mart, '299415947')
        ao, item = self.pool_clone(listing)
        self.run_cmd(SimpleNamespace(ok=True, data={'offer_id': '299999999'}))
        listing.refresh_from_db(); ao.refresh_from_db(); item.refresh_from_db()
        self.assertEqual(listing.store_listing_id, '299999999')
        self.assertEqual(ao.store_listing_id, '299999999')
        self.assertEqual(item.target_offer_id, '299999999')
        self.assertEqual(ao.status, OfferPoolActiveOfferStatus.ACTIVE)

    def test_pre_write_refusal_changes_nothing(self):
        listing = self.listing(self.mart, '299415947')
        before = listing.marketplace_expires_at
        _, out = self.run_cmd(SimpleNamespace(ok=False, error=SimpleNamespace(details={'delegation_outcome': 'rejected', 'error_code': 'renew_daily_cap_reached'})))
        listing.refresh_from_db()
        self.assertIn('SKIP', out)
        self.assertEqual(listing.marketplace_expires_at, before)

    def test_unknown_outcome_changes_nothing_and_is_reported(self):
        listing = self.listing(self.mart, '299415947')
        _, out = self.run_cmd(SimpleNamespace(ok=False, error=SimpleNamespace(details={'delegation_outcome': 'unknown'})))
        listing.refresh_from_db()
        self.assertIn('UNKNOWN', out)
        self.assertEqual(listing.store_listing_id, '299415947')
        self.assertNotIn('official_renewal', listing.raw_data or {})

    def test_shop_is_not_touched_by_default(self):
        self.listing(self.shop, '288000001')
        client, out = self.run_cmd(SimpleNamespace(ok=True, data={'offer_id': '288000001'}))
        client.renew_offer.assert_not_called()
        self.assertIn('candidates=0', out)

    def test_sale_evidence_blocks_renewal(self):
        from apps.orders.models import Order
        listing = self.listing(self.mart, '299415947')
        Order.objects.create(integration_account=self.mart, store_listing_id='299415947', price=Decimal('10'))
        client, out = self.run_cmd(SimpleNamespace(ok=True, data={'offer_id': '299415947'}))
        client.renew_offer.assert_not_called()


class MctClientRenewTests(TestCase):
    def test_renew_success_requires_offer_id_and_passes_expiry(self):
        from apps.integrations.providers.playerauctions import MctMartDelegationClient
        c = MctMartDelegationClient.__new__(MctMartDelegationClient)
        c._url = 'https://x/api/sda/pa-mart/delegate'; c._token = 't'
        c._encrypted_envelope = lambda payload: {'v': 1}
        resp = Mock(status_code=200, content=b'1')
        resp.json.return_value = {'ok': True, 'status': 'succeeded', 'offerId': '299999999', 'expiresAt': '2026-12-04T12:58:25.000Z'}
        with patch('apps.integrations.providers.playerauctions.requests.post', return_value=resp) as post:
            r = c.renew_offer('299415947', request_id='sda-renew-299415947-20261204-20261202')
        self.assertTrue(r.ok)
        self.assertEqual(r.data['offer_id'], '299999999')
        self.assertEqual(r.data['expires_at'], '2026-12-04T12:58:25.000Z')
        self.assertEqual(post.call_args.kwargs['json']['requestId'], 'sda-renew-299415947-20261204-20261202')
        self.assertEqual(post.call_args.kwargs['json']['action'], 'renew')

    def test_bad_offer_id_is_refused_locally(self):
        from apps.integrations.providers.playerauctions import MctMartDelegationClient
        c = MctMartDelegationClient.__new__(MctMartDelegationClient)
        r = c.renew_offer('0123', request_id='sda-renew-x-1-2')
        self.assertFalse(r.ok)
        self.assertEqual(r.error.details['delegation_outcome'], 'rejected')
