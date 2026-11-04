"""Missing expired Mart clones stay held until complete unsold recovery is verified."""
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential, PaGmailOrderEvent
from apps.inventory.models import Category, Game, OwnedProduct
from apps.orders.models import Order
from apps.listings.models import Listing
from apps.posting.models import (
    OfferPool, OfferPoolStatus, PoolOffer, PoolOfferStrategy,
    OfferPoolActiveOffer, OfferPoolActiveOfferStatus, OfferPoolItem, OfferPoolItemStatus,
    PoolDispatchAttempt, PoolDispatchStatus,
)
from apps.posting.services.pool.checker import _get_pa_active_count
from apps.posting.services.pool.replenisher import _PoolOfferContext
from apps.posting.services.pool.pa_mart_expiry import (
    RECOVERY_HOLD_REASON, expired_clone_block_reason, return_expired_mart_clones, _return_one,
)
from apps.posting.services.pool.pa_mart_claims import finalize_mart_claim_failure


class _MartPoolBase(TestCase):
    def make_pool(self, name):
        return OfferPool.objects.create(name=name, game=self.game, status=OfferPoolStatus.ACTIVE)

    def make_listing(self, *, account, remote_id):
        return Listing.objects.create(is_instant=True, integration_account=account, game=self.game,
            store_listing_id=remote_id, status='listed', title=remote_id, price=Decimal('10.00'), currency='USD')

    def make_owned(self, login):
        return OwnedProduct.objects.create(category=self.category, game=self.game, login=login, password='synthetic-only')

    def make_pool_offer(self, pool, *, listing, **values):
        return PoolOffer.objects.create(pool=pool, listing=listing, **values)

    def setUp(self):
        self.category = Category.objects.create(name='test-accounts', title='Test Accounts')
        self.game = Game.objects.create(name='Test Game', slug='test-game', category=self.category)
        self.mart = IntegrationAccount.objects.create(name='Mart', slug='playerauctions-csgosmurfkings', provider='playerauctions', role='sell')
        IntegrationCredential.objects.create(account=self.mart, credentials={'test': 'synthetic'})
        self.pool = self.make_pool('Mart Pool')
        self.template = self.make_listing(account=self.mart, remote_id='294000000')
        self.pool_offer = self.make_pool_offer(self.pool, listing=self.template, strategy=PoolOfferStrategy.CLONE, target_count=2, threshold=1, max_concurrent=2)
        self.n = 0

    def clone(self, *, expired_hours_ago):
        self.n += 1
        offer_id = str(295000000 + self.n)
        listing = self.make_listing(account=self.mart, remote_id=offer_id)
        listing.marketplace_expires_at = timezone.now() - timedelta(hours=expired_hours_ago)
        listing.save(update_fields=['marketplace_expires_at'])
        product = self.make_owned(f'mart-{self.n}@example.test')
        listing.listing_owned_products.create(owned_product=product)
        item = OfferPoolItem.objects.create(pool=self.pool, pool_offer=self.pool_offer, owned_product=product,
            status=OfferPoolItemStatus.PUSHED, target_offer_id=offer_id)
        return OfferPoolActiveOffer.objects.create(pool=self.pool, pool_offer=self.pool_offer, listing=listing, pool_item=item,
            store_listing_id=offer_id, status=OfferPoolActiveOfferStatus.ACTIVE)

    def check(self, live_ids=(), age=60, pages=1):
        client = Mock()
        client.uses_mct_official_offer_snapshot.return_value = True
        client.list_offers.return_value = SimpleNamespace(ok=True, data=[{'offerId': i} for i in live_ids],
            meta={'snapshot_age_seconds': age, 'pagination': {'current_page': 1, 'total_pages': pages}})
        with patch('apps.posting.services.pool.checker.get_or_build_client', return_value=client):
            return _get_pa_active_count(_PoolOfferContext(self.pool_offer))

    def assert_untouched(self, ao):
        ao.refresh_from_db(); ao.pool_item.refresh_from_db(); ao.listing.refresh_from_db()
        self.assertEqual(ao.status, OfferPoolActiveOfferStatus.ACTIVE)
        self.assertEqual(ao.pool_item.status, OfferPoolItemStatus.PUSHED)
        self.assertEqual(ao.pool_item.pool_offer_id, self.pool_offer.pk)
        self.assertEqual(ao.pool_item.target_offer_id, ao.store_listing_id)
        self.assertEqual(ao.listing.status, 'listed')
        self.assertEqual(list(ao.listing.listing_owned_products.values_list('owned_product_id', flat=True)), [ao.pool_item.owned_product_id])

    def claimed_item(self):
        token = uuid.uuid4()
        item = OfferPoolItem.objects.create(pool=self.pool, pool_offer=self.pool_offer, owned_product=self.make_owned(f'claim-{token}@example.test'),
            status=OfferPoolItemStatus.QUEUED, claim_token=token, claimed_at=timezone.now())
        PoolDispatchAttempt.objects.create(item=item, pool_offer=self.pool_offer, idempotency_key=token, operation='push', status='in_progress', request_fingerprint=token.hex)
        return item


class ExpiredMartPoolReturnTests(_MartPoolBase):
    def test_expired_missing_account_is_held_even_after_grace(self):
        ao = self.clone(expired_hours_ago=48)
        self.assertIsNone(self.check()); self.assert_untouched(ao)
        self.assertEqual(expired_clone_block_reason(ao), RECOVERY_HOLD_REASON)

    def test_positive_live_count_unchanged(self):
        ao = self.clone(expired_hours_ago=-240)
        self.assertEqual(self.check([ao.store_listing_id]), 1); self.assert_untouched(ao)

    def test_mixed_live_and_missing_does_not_partially_recycle(self):
        live = self.clone(expired_hours_ago=-240); missing = self.clone(expired_hours_ago=72)
        self.assertIsNone(self.check([live.store_listing_id]))
        self.assert_untouched(live); self.assert_untouched(missing)

    def test_partial_two_page_snapshot_does_not_return_inventory(self):
        ao = self.clone(expired_hours_ago=48)
        self.assertIsNone(self.check(pages=2)); self.assert_untouched(ao)
        outcome = return_expired_mart_clones([ao], snapshot_age_seconds=60, snapshot_meta={'pagination': {'current_page': 1, 'total_pages': 2}})
        self.assertEqual(outcome.returned, []); self.assertEqual(outcome.unresolved[ao.store_listing_id], 'snapshot_incomplete')

    def test_age_without_pagination_is_not_completeness_proof(self):
        ao = self.clone(expired_hours_ago=48)
        outcome = return_expired_mart_clones([ao], snapshot_age_seconds=60)
        self.assertEqual(outcome.returned, []); self.assertEqual(outcome.unresolved[ao.store_listing_id], 'snapshot_incomplete')
        self.assert_untouched(ao)

    def test_stale_or_invalid_age_changes_nothing(self):
        ao = self.clone(expired_hours_ago=48)
        for age in (5000, None, float('nan'), True, -1):
            self.assertIsNone(self.check(age=age)); self.assert_untouched(ao)

    def test_no_expiry_record_stays_held(self):
        ao = self.clone(expired_hours_ago=48); ao.listing.marketplace_expires_at = None
        ao.listing.save(update_fields=['marketplace_expires_at'])
        self.assertEqual(expired_clone_block_reason(ao), 'no_expiry_recorded')
        self.assertIsNone(self.check()); self.assert_untouched(ao)

    def test_recent_expiry_does_not_return_stock(self):
        ao = self.clone(expired_hours_ago=1)
        self.assertEqual(expired_clone_block_reason(ao), 'not_expired'); self.assertIsNone(self.check()); self.assert_untouched(ao)

    def test_product_link_mismatch_preserves_unrelated_association(self):
        ao = self.clone(expired_hours_ago=48); other = self.make_owned('other@example.test')
        ao.listing.listing_owned_products.all().delete(); ao.listing.listing_owned_products.create(owned_product=other)
        self.assertEqual(expired_clone_block_reason(ao), 'listing_product_mismatch')
        self.assertIsNone(self.check()); ao.pool_item.refresh_from_db()
        self.assertEqual(ao.pool_item.status, OfferPoolItemStatus.PUSHED)
        self.assertEqual(list(ao.listing.listing_owned_products.values_list('owned_product_id', flat=True)), [other.pk])

    def test_lane_mismatch_stays_held(self):
        ao = self.clone(expired_hours_ago=48)
        other_lane = self.make_pool_offer(self.pool, listing=self.make_listing(account=self.mart, remote_id='294999999'), strategy=PoolOfferStrategy.CLONE, target_count=1, threshold=1, max_concurrent=1)
        ao.pool_item.pool_offer = other_lane; ao.pool_item.save(update_fields=['pool_offer'])
        self.assertEqual(expired_clone_block_reason(ao), 'pool_lane_mismatch')
        self.assertIsNone(self.check()); ao.pool_item.refresh_from_db(); self.assertEqual(ao.pool_item.status, OfferPoolItemStatus.PUSHED)

    def test_blank_target_id_not_accepted(self):
        ao = self.clone(expired_hours_ago=48); ao.pool_item.target_offer_id = ''; ao.pool_item.save(update_fields=['target_offer_id'])
        self.assertEqual(expired_clone_block_reason(ao), 'item_target_mismatch'); self.assertIsNone(self.check())

    def test_sold_and_protected_product_statuses_stay_held(self):
        ao = self.clone(expired_hours_ago=48)
        for status in ('sold', 'multiple_sold', 'replaced', 'recovered', 'lost', 'banned'):
            ao.pool_item.owned_product.status = status; ao.pool_item.owned_product.save(update_fields=['status'])
            self.assertEqual(expired_clone_block_reason(ao), 'product_sold_or_protected'); self.assertIsNone(self.check()); self.assert_untouched(ao)

    def test_sibling_active_clone_blocks_return(self):
        ao = self.clone(expired_hours_ago=48)
        OfferPoolActiveOffer.objects.create(pool=self.pool, pool_offer=self.pool_offer, listing=ao.listing, pool_item=ao.pool_item, store_listing_id='295999999', status='active')
        self.assertEqual(expired_clone_block_reason(ao), 'other_active_clone'); self.assertIsNone(self.check()); self.assert_untouched(ao)

    def test_unmatched_signed_event_and_late_sale_link_are_preserved(self):
        ao = self.clone(expired_hours_ago=48); ao.listing.title = 'Fixture #ABC123'; ao.listing.save(update_fields=['title'])
        PaGmailOrderEvent.objects.create(event_id=uuid.uuid4(), source='synthetic', external_order_id='fixture-order', tracking_code='#ABC123', observed_at_ms=1, disposition='unmatched')
        self.assertEqual(expired_clone_block_reason(ao), 'signed_order_event'); self.assertIsNone(self.check()); self.assert_untouched(ao)

    def test_direct_helper_and_environment_flags_cannot_bypass_hold(self):
        ao = self.clone(expired_hours_ago=48)
        with patch.dict('os.environ', {'PA_MART_EXPIRY_RETURN_ENABLED': 'true', 'PA_MART_CREATE_HOLD': 'false'}):
            self.assertEqual(_return_one(ao.pk, now=timezone.now()), RECOVERY_HOLD_REASON)
            self.assertIsNone(self.check()); self.assert_untouched(ao)

    def test_no_return_means_sibling_lane_gets_no_new_pending_stock(self):
        ao = self.clone(expired_hours_ago=48)
        self.assertIsNone(self.check()); self.assertFalse(OfferPoolItem.objects.filter(pool=self.pool, status='pending', pool_offer__isnull=True).exists())
        self.assert_untouched(ao)

    def test_order_on_offer_remains_protected(self):
        ao = self.clone(expired_hours_ago=48)
        with patch('apps.posting.services.pool.pa_mart_expiry.Order.objects.filter') as orders:
            orders.return_value.exists.return_value = True
            self.assertEqual(expired_clone_block_reason(ao), 'order_on_offer')
        self.assertEqual(expired_clone_block_reason(ao), RECOVERY_HOLD_REASON)


class PaPreWriteRefusalDefersRefillTests(_MartPoolBase):
    def _post(self, details, callback=None):
        from apps.posting.services.pool import replenisher
        item = self.claimed_item()
        client = Mock(); client.uses_official_offer_api_only.return_value = True
        provider = Mock()
        result = SimpleNamespace(ok=False, data=None, error=SimpleNamespace(details=details))
        provider.create_listing.side_effect = (lambda *a, **k: callback(item, result)) if callback else None
        provider.create_listing.return_value = result
        pool = SimpleNamespace(aggregate=self.pool, listing=self.template)
        with patch.object(replenisher, 'pool_clone_tracking_code', return_value='#ABC123'), patch('apps.integrations.providers.registry.get_provider', return_value=provider):
            self.assertEqual(replenisher._post_pa_excel_row(pool, client, item, {'Title': 'Fixture'}, None), 0)
        item.refresh_from_db()
        return item

    def test_generic_rejected_http200_is_not_safe_to_retry(self):
        item = self._post({'delegation_outcome': 'rejected', 'error_code': 'create_failed_http_200'})
        self.assertEqual(item.status, 'failed'); self.assertEqual(item.remote_state, 'unknown')
        self.assertEqual(item.dispatch_attempts.get().status, PoolDispatchStatus.UNKNOWN)

    def test_unknown_and_offer_bearing_response_stay_failed_unknown(self):
        for details in ({'delegation_outcome': 'unknown'}, {'delegation_outcome': 'rejected', 'offerId': '295000099'}):
            item = self._post(details); self.assertEqual(item.status, 'failed'); self.assertEqual(item.remote_state, 'unknown')

    def test_only_local_pretransport_refusal_releases_exact_claim(self):
        item = self._post({'delegation_outcome': 'rejected', 'no_write_proof': 'sda_local_pretransport', 'error_code': 'mart_create_held'})
        self.assertEqual(item.status, 'pending'); self.assertEqual(item.remote_state, 'absent'); self.assertIsNone(item.pool_offer_id)
        self.assertEqual(item.dispatch_attempts.get().status, PoolDispatchStatus.FAILED)

    def test_contradictory_offer_identity_cannot_release_even_with_proof_label(self):
        item = self._post({'delegation_outcome': 'rejected', 'no_write_proof': 'sda_local_pretransport', 'error_code': 'mart_create_held', 'offerId': '295000099'})
        self.assertEqual(item.status, 'failed'); self.assertEqual(item.remote_state, 'unknown')

    def test_stale_response_does_not_clear_new_worker_claim(self):
        new_token = uuid.uuid4()
        def supersede(item, result):
            OfferPoolItem.objects.filter(pk=item.pk).update(claim_token=new_token)
            return result
        item = self._post({'delegation_outcome': 'unknown'}, supersede)
        self.assertEqual(item.status, 'queued'); self.assertEqual(item.claim_token, new_token)
        self.assertEqual(item.dispatch_attempts.get().status, 'in_progress')

    def test_failure_replay_and_wrong_attempt_are_noops(self):
        item = self.claimed_item(); token = item.claim_token
        self.assertFalse(finalize_mart_claim_failure(item, expected_token=uuid.uuid4(), local_pretransport=True))
        self.assertTrue(finalize_mart_claim_failure(item, expected_token=token, local_pretransport=True))
        self.assertFalse(finalize_mart_claim_failure(item, expected_token=token, local_pretransport=True))
        item.refresh_from_db(); self.assertEqual(item.status, 'pending')

    def test_missing_or_terminal_attempt_never_releases_claim(self):
        item = self.claimed_item(); token = item.claim_token
        item.dispatch_attempts.update(status='succeeded')
        self.assertFalse(finalize_mart_claim_failure(item, expected_token=token, local_pretransport=True))
        item.refresh_from_db(); self.assertEqual(item.status, 'queued')

    def test_protected_stock_is_not_released_even_before_transport(self):
        item = self.claimed_item(); item.owned_product.status = 'sold'; item.owned_product.save(update_fields=['status'])
        self.assertTrue(finalize_mart_claim_failure(item, expected_token=item.claim_token, local_pretransport=True))
        item.refresh_from_db(); self.assertEqual(item.status, 'failed'); self.assertEqual(item.remote_state, 'unknown')

    def test_raw_provider_text_is_not_persisted(self):
        item = self._post({'delegation_outcome': 'unknown', 'provider_message': 'synthetic-sensitive-value'})
        self.assertNotIn('synthetic-sensitive-value', item.error_message)
        self.assertNotIn('synthetic-sensitive-value', item.dispatch_attempts.get().error_message)

    def test_real_sdk_local_hold_round_trip_releases_without_transport(self):
        from apps.integrations.providers.playerauctions import MctMartDelegationClient
        client = MctMartDelegationClient(url='https://fixture.test/api/sda/pa-mart/delegate', token='synthetic', key=b'x' * 32)
        with patch.dict('os.environ', {'PA_MART_CREATE_HOLD': 'true'}), patch('apps.integrations.providers.playerauctions.requests.post') as transport:
            result = client.create_offer('account', {})
            item = self._post({}, callback=lambda _item, _result: result)
            transport.assert_not_called()
        self.assertEqual(item.status, 'pending'); self.assertEqual(item.remote_state, 'absent')

    def test_safe_unknown_request_identifier_is_durable(self):
        request_id = 'a' * 40
        item = self._post({'delegation_outcome': 'unknown', 'request_id': request_id})
        self.assertIn(request_id, item.error_message)
        self.assertIn(request_id, item.dispatch_attempts.get().error_message)

    def test_unvalidated_identifier_is_not_persisted(self):
        item = self._post({'delegation_outcome': 'unknown', 'request_id': 'synthetic-sensitive-value'})
        self.assertNotIn('synthetic-sensitive-value', item.error_message)
