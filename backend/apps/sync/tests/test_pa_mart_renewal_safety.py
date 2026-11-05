"""Synthetic-only safety checks: all marketplace transport is a mock.

TransactionTestCase is essential: Django TestCase's outer transaction must be
refused by production renewal rather than silently treating a savepoint as a
committed claim. Orders use bulk_create to avoid unrelated lifecycle signals.
"""
import threading
import uuid
from datetime import timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential, PaGmailOrderEvent
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
from apps.orders.models import Order
from apps.posting.models import (
    OfferPool, OfferPoolActiveOffer, OfferPoolItem, PoolDispatchAttempt,
    PoolOffer, PoolSaleEvent,
)
from apps.sync.models import PaMartRenewalAttempt, SyncFeatureFlag
from apps.sync.services.pa_mart_renewal import mart_renewal_request_id, renew_mart_listing
from apps.sync.services.shared.feature_flags import SyncFlag

SERVICE = 'apps.sync.services.pa_mart_renewal'


class PaMartRenewalSafetyTests(TransactionTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.expiry = self.now + timedelta(hours=72)
        self.verified = self.now + timedelta(days=30)
        self.category = Category.objects.create(name='renew-test', title='Synthetic Accounts')
        self.game = Game.objects.create(name='Synthetic Game', slug='renew-test', category=self.category)
        self.account = IntegrationAccount.objects.create(name='Synthetic Mart', slug='playerauctions-csgosmurfkings', provider='playerauctions', role='sell')
        IntegrationCredential.objects.create(account=self.account, credentials={'synthetic': True})
        self.template = self.make_listing('294000000')
        self.pool = OfferPool.objects.create(name='Synthetic Pool', game=self.game, status='active')
        self.lane = PoolOffer.objects.create(pool=self.pool, listing=self.template, strategy='clone', status='active', target_count=2, threshold=1, max_concurrent=2)
        self.listing = self.make_listing('295000001', expiry=self.expiry)
        self.product = self.make_product('renew-synthetic')
        ListingOwnedProduct.objects.create(listing=self.listing, owned_product=self.product)
        self.item = OfferPoolItem.objects.create(pool=self.pool, pool_offer=self.lane, owned_product=self.product, status='pushed', target_offer_id=self.listing.store_listing_id)
        self.clone = OfferPoolActiveOffer.objects.create(pool=self.pool, pool_offer=self.lane, listing=self.listing, pool_item=self.item, store_listing_id=self.listing.store_listing_id, status='active')
        SyncFeatureFlag.objects.update_or_create(key=SyncFlag.RENEW_EXPIRING_PA, defaults={'is_enabled': True})
        self.client = Mock()
        self.client.renew_offer.return_value = self.success()

    def make_listing(self, offer_id, *, expiry=None, account=None):
        return Listing.objects.create(integration_account=account or self.account, game=self.game, is_instant=True, status='listed', store_listing_id=offer_id, title='Synthetic #ABC123', price='10.00', marketplace_expires_at=expiry)

    def make_product(self, login):
        return OwnedProduct.objects.create(category=self.category, game=self.game, login=login, password='synthetic-only', status='listed')

    def success(self, offer_id='295000001', expiry=None):
        return SimpleNamespace(ok=True, data={'offer_id': offer_id, 'expires_at': (expiry or self.verified).isoformat()}, error=None)

    def error(self, details):
        return SimpleNamespace(ok=False, data=None, error=SimpleNamespace(details=details))

    def run_renew(self):
        return renew_mart_listing(self.listing.pk, self.client)

    def attempt(self):
        return PaMartRenewalAttempt.objects.get(listing=self.listing)

    def make_attempt(self, *, status='unknown', listing=None, old_id=None, new_id='', expiry=None):
        listing = listing or self.listing
        expiry = expiry or self.expiry
        old_id = old_id or listing.store_listing_id
        return PaMartRenewalAttempt.objects.create(listing=listing, integration_account=listing.integration_account, old_offer_id=old_id, new_offer_id=new_id, previous_expires_at=expiry, request_id=mart_renewal_request_id(old_id, expiry), status=status, reason_code='synthetic_fixture')

    def order(self, **values):
        defaults = dict(integration_account=self.account, store_order_id='synthetic-' + uuid.uuid4().hex, price='10.00', status='pending')
        defaults.update(values)
        return Order.objects.bulk_create([Order(**defaults)])[0]

    def assert_stock_unchanged(self):
        self.listing.refresh_from_db(); self.item.refresh_from_db(); self.clone.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.listing.store_listing_id, '295000001')
        self.assertEqual(self.listing.marketplace_expires_at, self.expiry)
        self.assertEqual(self.listing.status, 'listed')
        self.assertEqual(self.clone.store_listing_id, '295000001')
        self.assertEqual(self.item.target_offer_id, '295000001')
        self.assertEqual(self.item.status, 'pushed')
        self.assertEqual(self.item.live_owned_product_id, self.product.pk)
        self.assertEqual(list(self.listing.listing_owned_products.values_list('owned_product_id', flat=True)), [self.product.pk])

    def assert_rejected_without_send(self):
        self.assertEqual(self.run_renew()[0], 'rejected')
        self.client.renew_offer.assert_not_called()

    def test_same_id_verified_extension_updates_only_exact_rows(self):
        self.assertEqual(self.run_renew()[0], 'renewed')
        self.listing.refresh_from_db(); self.item.refresh_from_db(); self.clone.refresh_from_db(); self.product.refresh_from_db()
        attempt = self.attempt()
        self.assertEqual(attempt.status, 'succeeded')
        self.assertEqual(attempt.old_offer_id, attempt.new_offer_id)
        self.assertEqual(attempt.previous_expires_at, self.expiry)
        self.assertEqual(attempt.verified_expires_at, self.verified)
        self.assertEqual(self.listing.marketplace_expires_at, self.verified)
        self.assertEqual((self.listing.status, self.item.status, self.clone.status, self.product.status), ('listed', 'pushed', 'active', 'listed'))
        self.assertEqual(self.item.live_owned_product_id, self.product.pk)
        self.assertEqual(PoolSaleEvent.objects.count(), 0)
        self.assertEqual(OfferPoolItem.objects.count(), 1)

    def test_replacement_id_updates_only_exact_listing_clone_item(self):
        other = self.make_listing('295000009', expiry=self.expiry)
        other_product = self.make_product('other-synthetic')
        ListingOwnedProduct.objects.create(listing=other, owned_product=other_product)
        other_item = OfferPoolItem.objects.create(pool=self.pool, pool_offer=self.lane, owned_product=other_product, status='pushed', target_offer_id=other.store_listing_id)
        other_clone = OfferPoolActiveOffer.objects.create(pool=self.pool, pool_offer=self.lane, pool_item=other_item, listing=other, store_listing_id=other.store_listing_id, status='active')
        self.client.renew_offer.return_value = self.success('295000002')
        self.assertEqual(self.run_renew()[0], 'renewed')
        self.listing.refresh_from_db(); self.clone.refresh_from_db(); self.item.refresh_from_db()
        other.refresh_from_db(); other_clone.refresh_from_db(); other_item.refresh_from_db(); self.template.refresh_from_db()
        self.assertEqual((self.listing.store_listing_id, self.clone.store_listing_id, self.item.target_offer_id), ('295000002',) * 3)
        self.assertEqual((other.store_listing_id, other_clone.store_listing_id, other_item.target_offer_id), ('295000009',) * 3)
        self.assertEqual(self.template.store_listing_id, '294000000')
        self.assertEqual((self.attempt().old_offer_id, self.attempt().new_offer_id), ('295000001', '295000002'))

    def test_ownership_link_mismatch_is_rejected(self):
        other = self.make_product('wrong-owner')
        ListingOwnedProduct.objects.filter(listing=self.listing).delete()
        ListingOwnedProduct.objects.create(listing=self.listing, owned_product=other)
        self.assert_rejected_without_send()

    def test_live_owner_missing_is_rejected(self):
        OfferPoolItem.objects.filter(pk=self.item.pk).update(live_owned_product=None)
        self.assert_rejected_without_send()

    def test_all_sold_or_protected_statuses_are_rejected(self):
        for status in ('sold', 'multiple_sold', 'replaced', 'recovered', 'lost', 'banned'):
            with self.subTest(status=status):
                OwnedProduct.objects.filter(pk=self.product.pk).update(status=status)
                self.assert_rejected_without_send()

    def test_pending_order_exact_current_id_without_product_link_blocks(self):
        self.order(store_listing_id='295000001')
        self.assert_rejected_without_send()

    def test_historical_stock_order_on_product_blocks(self):
        self.order(owned_product=self.product, store_listing_id='293000001', status='cancelled')
        self.assert_rejected_without_send()

    def test_historical_ledger_id_order_blocks_even_without_product_fk(self):
        self.make_attempt(status='succeeded', old_id='293000001', new_id='295000001', expiry=self.expiry - timedelta(days=30))
        self.order(store_listing_id='293000001')
        self.assert_rejected_without_send()

    def test_historical_clone_id_order_blocks(self):
        old = self.make_listing('293000002')
        OfferPoolActiveOffer.objects.create(pool=self.pool, pool_offer=self.lane, listing=old, pool_item=self.item, store_listing_id=old.store_listing_id, status='delisted')
        self.order(store_listing_id='293000002')
        self.assert_rejected_without_send()

    def test_failed_clone_is_not_a_current_account_candidate(self):
        OfferPoolActiveOffer.objects.filter(pk=self.clone.pk).update(status='failed')
        self.assert_rejected_without_send()

    def test_item_failed_or_consumed_is_not_eligible(self):
        for status in ('failed', 'consumed'):
            OfferPoolItem.objects.filter(pk=self.item.pk).update(status=status)
            self.assert_rejected_without_send()

    def test_root_template_never_renews_without_exact_clone(self):
        self.assertEqual(renew_mart_listing(self.template.pk, self.client)[0], 'rejected')
        self.client.renew_offer.assert_not_called()

    def test_paused_lane_pool_and_inactive_account_block(self):
        for model, obj, field, bad, good in (
            (PoolOffer, self.lane, 'status', 'paused', 'active'),
            (OfferPool, self.pool, 'status', 'paused', 'active'),
            (IntegrationAccount, self.account, 'is_active', False, True),
        ):
            with self.subTest(model=model.__name__):
                model.objects.filter(pk=obj.pk).update(**{field: bad})
                self.assert_rejected_without_send()
                model.objects.filter(pk=obj.pk).update(**{field: good})

    def test_claim_or_unknown_dispatch_blocks(self):
        OfferPoolItem.objects.filter(pk=self.item.pk).update(claim_token=uuid.uuid4())
        self.assert_rejected_without_send()
        OfferPoolItem.objects.filter(pk=self.item.pk).update(claim_token=None)
        PoolDispatchAttempt.objects.create(item=self.item, pool_offer=self.lane, operation='push', status='unknown', request_fingerprint='0' * 64)
        self.assert_rejected_without_send()

    def test_historical_sold_clone_and_sale_event_block(self):
        historical = OfferPoolActiveOffer.objects.create(pool=self.pool, pool_offer=self.lane, listing=self.listing, pool_item=self.item, store_listing_id='293000001', status='sold')
        self.assert_rejected_without_send()
        OfferPoolActiveOffer.objects.filter(pk=historical.pk).update(status='delisted')
        PoolSaleEvent.objects.create(event_key='synthetic-sale', listing=self.listing, pool_item=self.item)
        self.assert_rejected_without_send()

    def test_unmatched_signed_gmail_event_blocks_stock(self):
        PaGmailOrderEvent.objects.create(event_id=uuid.uuid4(), source='synthetic', external_order_id='synthetic-mail', tracking_code='#ABC123', observed_at_ms=1, disposition='unmatched')
        self.assert_rejected_without_send()

    def test_recorded_missing_or_past_expiry_never_sends(self):
        for expiry in (None, self.now - timedelta(hours=1)):
            Listing.objects.filter(pk=self.listing.pk).update(marketplace_expires_at=expiry)
            self.assert_rejected_without_send()

    def test_missing_malformed_naive_past_no_extension_and_far_expiry_unknown(self):
        values = (None, 'garbage', self.verified.replace(tzinfo=None).isoformat(), (self.now - timedelta(hours=1)).isoformat(), self.expiry.isoformat(), (self.now + timedelta(days=36)).isoformat())
        for value in values:
            with self.subTest(expiry=value):
                self.client.renew_offer.return_value = SimpleNamespace(ok=True, data={'offer_id': '295000002', 'expires_at': value})
                self.assertEqual(self.run_renew()[0], 'unknown')
                self.assertEqual(self.attempt().status, 'unknown')
                self.assertIsNone(self.attempt().verified_expires_at)
                self.assert_stock_unchanged()
                # Isolate synthetic cycles; production never deletes a hold.
                PaMartRenewalAttempt.objects.all().delete()

    def test_unknown_next_day_retains_same_attempt_and_request_id(self):
        self.client.renew_offer.return_value = self.error({'delegation_outcome': 'rejected', 'error_code': 'external_failure'})
        self.assertEqual(self.run_renew()[0], 'unknown')
        attempt = self.attempt()
        with patch(SERVICE + '.timezone.now', return_value=self.now + timedelta(days=1)):
            self.assertEqual(self.run_renew()[0], 'unknown')
        self.assertEqual(self.client.renew_offer.call_count, 1)
        self.assertEqual(self.attempt().request_id, attempt.request_id)
        self.assert_stock_unchanged()

    def test_unknown_hold_blocks_even_after_other_path_changes_cycle(self):
        attempt = self.make_attempt()
        Listing.objects.filter(pk=self.listing.pk).update(store_listing_id='295000002', marketplace_expires_at=self.expiry + timedelta(hours=1))
        self.assertEqual(self.run_renew()[0], 'unknown')
        self.client.renew_offer.assert_not_called()
        self.assertEqual(self.attempt().pk, attempt.pk)

    def test_existing_pending_claim_is_never_resent(self):
        attempt = self.make_attempt(status='pending')
        for _ in range(2):
            self.assertEqual(self.run_renew()[0], 'unknown')
        self.client.renew_offer.assert_not_called()
        self.assertEqual(self.attempt().request_id, attempt.request_id)

    def test_replacement_current_listing_collision_is_unknown(self):
        self.make_listing('295000002')
        self.client.renew_offer.return_value = self.success('295000002')
        self.assertEqual(self.run_renew()[0], 'unknown')
        self.assertEqual(self.attempt().new_offer_id, '295000002')
        self.assertEqual(self.attempt().verified_expires_at, self.verified)
        self.assert_stock_unchanged()

    def test_replacement_historical_alias_collision_is_unknown(self):
        other = self.make_listing('295000009')
        self.make_attempt(status='succeeded', listing=other, old_id='295000002', new_id='295000009', expiry=self.expiry - timedelta(days=30))
        self.client.renew_offer.return_value = self.success('295000002')
        self.assertEqual(self.run_renew()[0], 'unknown')
        self.assert_stock_unchanged()

    def test_sale_appearing_during_http_preserves_verified_identity_but_no_local_update(self):
        def sold(*args, **kwargs):
            self.order(owned_product=self.product, store_listing_id='295000001')
            return self.success('295000002')
        self.client.renew_offer.side_effect = sold
        self.assertEqual(self.run_renew()[0], 'unknown')
        attempt = self.attempt()
        self.assertEqual((attempt.status, attempt.new_offer_id, attempt.verified_expires_at), ('unknown', '295000002', self.verified))
        self.assert_stock_unchanged()

    def test_ownership_changed_during_http_is_unknown_without_mutation(self):
        def moved(*args, **kwargs):
            OfferPoolItem.objects.filter(pk=self.item.pk).update(live_owned_product=None)
            return self.success('295000002')
        self.client.renew_offer.side_effect = moved
        self.assertEqual(self.run_renew()[0], 'unknown')
        self.listing.refresh_from_db(); self.item.refresh_from_db()
        self.assertEqual(self.listing.store_listing_id, '295000001')
        self.assertIsNone(self.item.live_owned_product_id)
        self.assertEqual(self.attempt().new_offer_id, '295000002')

    def test_only_literal_local_no_write_proof_and_trusted_reason_rejected(self):
        self.client.renew_offer.return_value = self.error({'delegation_outcome': 'rejected', 'no_write_proof': 'sda_local_pretransport', 'error_code': 'renew_invalid_request_id'})
        self.assertEqual(self.run_renew()[0], 'rejected')
        self.assertEqual(self.attempt().status, 'rejected')
        self.assert_stock_unchanged()
        self.assertEqual(self.run_renew()[0], 'rejected')
        self.assertEqual(self.client.renew_offer.call_count, 1)

    def test_external_rejections_and_contradictory_proof_remain_unknown(self):
        for details in (
            {'delegation_outcome': 'rejected'},
            {'delegation_outcome': 'rejected', 'no_write_proof': True, 'error_code': 'renew_invalid_request_id'},
            {'delegation_outcome': 'rejected', 'no_write_proof': 'sda_local_pretransport', 'error_code': 'external_rejection'},
            {'delegation_outcome': 'rejected', 'no_write_proof': 'sda_local_pretransport', 'error_code': 'renew_invalid_request_id', 'offerId': '295000002'},
        ):
            self.client.renew_offer.return_value = self.error(details)
            self.assertEqual(self.run_renew()[0], 'unknown')
            self.assertEqual(self.attempt().status, 'unknown')
            PaMartRenewalAttempt.objects.all().delete()

    def test_transport_exception_is_sanitized_and_durable_unknown(self):
        secret_marker = 'synthetic-secret-must-not-be-printed'
        self.client.renew_offer.side_effect = RuntimeError(secret_marker)
        outcome, message = self.run_renew()
        self.assertEqual(outcome, 'unknown')
        self.assertNotIn(secret_marker, message)
        self.assertNotIn(secret_marker, self.attempt().reason_code)
        self.assertEqual(self.attempt().status, 'unknown')
        self.assert_stock_unchanged()

    def test_missing_disabled_or_unreadable_feature_flag_fails_closed(self):
        SyncFeatureFlag.objects.filter(key=SyncFlag.RENEW_EXPIRING_PA).delete()
        self.assert_rejected_without_send()
        SyncFeatureFlag.objects.create(key=SyncFlag.RENEW_EXPIRING_PA, is_enabled=False)
        self.assert_rejected_without_send()
        with patch('apps.sync.models.SyncFeatureFlag.objects.filter', side_effect=RuntimeError('synthetic-db-exception')):
            self.assert_rejected_without_send()
        with patch(SERVICE + '.is_sync_feature_enabled', side_effect=RuntimeError('synthetic-lookup-exception')):
            self.assert_rejected_without_send()

    def test_enclosing_atomic_is_refused_and_creates_no_attempt(self):
        with transaction.atomic():
            outcome, message = self.run_renew()
        self.assertEqual(outcome, 'rejected')
        self.assertIn('enclosing_transaction_refused', message)
        self.client.renew_offer.assert_not_called()
        self.assertFalse(PaMartRenewalAttempt.objects.exists())

    def test_pending_claim_is_committed_before_http_visible_to_other_connection(self):
        seen, errors = [], []
        def read_committed():
            close_old_connections()
            try:
                seen.extend(PaMartRenewalAttempt.objects.filter(listing_id=self.listing.pk).values_list('status', 'request_id'))
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                close_old_connections()
        def transport(*args, **kwargs):
            reader = threading.Thread(target=read_committed)
            reader.start(); reader.join(timeout=5)
            self.assertFalse(reader.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(seen, [('pending', kwargs['request_id'])])
            return self.success()
        self.client.renew_offer.side_effect = transport
        self.assertEqual(self.run_renew()[0], 'renewed')

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_workers_send_once_and_keep_stable_pending_identity(self):
        entered, release = threading.Event(), threading.Event()
        outcomes, failures = [], []
        def transport(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError('synthetic-test-timeout')
            return self.error({'delegation_outcome': 'unknown'})
        self.client.renew_offer.side_effect = transport
        def worker():
            close_old_connections()
            try:
                outcomes.append(renew_mart_listing(self.listing.pk, self.client)[0])
            except Exception as exc:
                failures.append(type(exc).__name__)
            finally:
                close_old_connections()
        first, second = threading.Thread(target=worker), threading.Thread(target=worker)
        first.start()
        try:
            self.assertTrue(entered.wait(timeout=5))
            second.start()
        finally:
            release.set()
            first.join(timeout=15)
            if second.ident is not None:
                second.join(timeout=15)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(outcomes, ['unknown', 'unknown'])
        self.assertEqual(self.client.renew_offer.call_count, 1)
        self.assertEqual(self.attempt().request_id, self.client.renew_offer.call_args.kwargs['request_id'])
        self.assert_stock_unchanged()

    def test_request_id_uses_full_utc_expiry_and_ignores_invocation_day(self):
        rid = mart_renewal_request_id('295000001', self.expiry, self.now)
        self.assertEqual(rid, mart_renewal_request_id('295000001', self.expiry, self.now + timedelta(days=1)))
        self.assertEqual(rid, mart_renewal_request_id('295000001', self.expiry.astimezone(dt_timezone(timedelta(hours=5)))))
        self.assertNotEqual(rid, mart_renewal_request_id('295000001', self.expiry + timedelta(microseconds=1)))
        self.assertLessEqual(len(rid), 128)
        self.assertTrue(rid.isascii())
        self.assertRegex(rid, r'^sda-renew-295000001-[0-9a-f]{64}$')

    def test_ledger_protects_historical_listing_and_account(self):
        self.make_attempt(status='succeeded')
        with self.assertRaises(ProtectedError):
            self.listing.delete()
        with self.assertRaises(ProtectedError):
            self.account.delete()

    def test_database_unique_cycle_and_unique_request_id(self):
        attempt = self.make_attempt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaMartRenewalAttempt.objects.create(listing=self.listing, integration_account=self.account, old_offer_id='295000001', previous_expires_at=self.expiry, request_id='synthetic-different-request-id')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaMartRenewalAttempt.objects.create(listing=self.listing, integration_account=self.account, old_offer_id='295000002', previous_expires_at=self.expiry, request_id=attempt.request_id)
        self.assertEqual(PaMartRenewalAttempt.objects.count(), 1)

    def test_finalization_rollback_keeps_committed_claim_and_never_resends(self):
        from apps.sync.services import pa_mart_renewal
        real_finish = pa_mart_renewal._finish
        def fail_success(attempt, status, reason, **kwargs):
            if status == 'succeeded':
                raise RuntimeError('synthetic-finalization-failure')
            return real_finish(attempt, status, reason, **kwargs)
        with patch(SERVICE + '._finish', side_effect=fail_success):
            self.assertEqual(self.run_renew()[0], 'unknown')
        attempt = self.attempt()
        self.assertEqual(attempt.status, 'unknown')
        self.assertEqual(attempt.new_offer_id, '295000001')
        self.assertEqual(attempt.verified_expires_at, self.verified)
        self.assert_stock_unchanged()
        self.assertEqual(self.run_renew()[0], 'unknown')
        self.assertEqual(self.client.renew_offer.call_count, 1)

    def test_claim_persist_failure_never_calls_transport(self):
        with patch('apps.sync.models.PaMartRenewalAttempt.objects.create', side_effect=RuntimeError('synthetic-claim-db-failure')):
            self.assertEqual(self.run_renew()[0], 'unknown')
        self.client.renew_offer.assert_not_called()
        self.assertFalse(PaMartRenewalAttempt.objects.exists())
        self.assert_stock_unchanged()

    def test_flag_disabled_during_send_keeps_unknown_and_verified_evidence(self):
        def disable(*args, **kwargs):
            SyncFeatureFlag.objects.filter(key=SyncFlag.RENEW_EXPIRING_PA).update(is_enabled=False)
            return self.success('295000002')
        self.client.renew_offer.side_effect = disable
        self.assertEqual(self.run_renew()[0], 'unknown')
        self.assertEqual(self.attempt().new_offer_id, '295000002')
        self.assertEqual(self.attempt().verified_expires_at, self.verified)
        self.assert_stock_unchanged()
