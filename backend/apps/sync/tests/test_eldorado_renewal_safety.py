"""Synthetic-only safety tests: no marketplace transport or production settings.

TransactionTestCase deliberately tests real commit boundaries. A simulated
process crash is BaseException, leaving the committed pending hold untouched.
SQLite cannot prove row-lock concurrency; that test requires select_for_update.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import importlib
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from apis_sdk.clients.marketplaces.eldorado.models import EldoradoOfferCredentialsResponse, EldoradoPrivateOffer
from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.listings.models import Listing
from apps.orders.models import Order
from apps.posting.models import PoolSaleEvent
from apps.sync.models import MarketplaceRenewalCheck as Check, SyncFeatureFlag
from apps.sync.services.eldorado import renewal as R
from apps.sync.services.shared.feature_flags import SyncFlag

OID = '3d952183-48cb-476e-ab3f-08df24631e7b'
DETAIL = {
    'accountDetails': {'accountLogin': 'synthetic-account', 'accountPassword': 'fixture-only'},
    'emailDetails': None,
    'mfaDetails': {'method': 'synthetic', 'codes': ['fixture-only']},
    'additionalInfo': '  preserve spacing  ',
    'unknownCredentialField': {'keep': [None, 'fixture-only']},
}


def snapshot(expiry, **changes):
    return {
        'id': OID, 'offerState': 'Active', 'expireDate': expiry.isoformat(),
        'gameId': '106', 'category': 'Account', 'offerTitle': 'Authoritative live title',
        'description': None, 'guaranteedDeliveryTime': 'Instant',
        'quantity': 1, 'minQuantity': 1, 'pricePerUnit': {'amount': 12.5, 'currency': 'USD'},
        'volumeDiscounts': [], 'hasOriginalEmail': False,
        'mainOfferImage': None, 'offerImages': [],
        'tradeEnvironmentValues': [], 'attributes': [], **changes,
    }


def response(live=None, *, ok=True, status=200, error=None):
    data = EldoradoPrivateOffer.model_validate({'offer': live}) if ok and live is not None else None
    return SimpleNamespace(ok=ok, data=data, status_code=status, error=error)


class FakeLeasedClient:
    """Asserts every logical provider call uses the one client and outer lease."""
    def __init__(self, testcase, expiry, verified):
        self.testcase = testcase
        self.lease_depth = 0
        self.admitted = True
        self.events = []
        self.private_responses = [response(snapshot(expiry)), response(snapshot(verified))]
        self.get_private_offer = Mock(side_effect=self._read)
        creds = EldoradoOfferCredentialsResponse.model_validate({'accountDeliveryDetails': [
            {'id': 'synthetic-entry', 'structuredDetails': deepcopy(DETAIL)},
        ]})
        self.credentials = SimpleNamespace(ok=True, data=creds, error=None)
        self.get_offer_account_details = Mock(side_effect=self._credentials)
        self.update_offer_once = Mock(side_effect=self._update)
        self.update_offer = Mock(side_effect=AssertionError('legacy retry path forbidden'))

    @contextmanager
    def offer_mutation(self, offer_id):
        self.testcase.assertEqual(offer_id, OID)
        self.testcase.assertEqual(self.lease_depth, 0)
        self.events.append('lease_enter')
        self.lease_depth += 1
        try:
            yield self.admitted
        finally:
            self.lease_depth -= 1
            self.events.append('lease_exit')

    def boundary(self, name, offer_id):
        self.testcase.assertEqual(offer_id, OID)
        self.testcase.assertEqual(self.lease_depth, 1)
        self.testcase.assertFalse(connection.in_atomic_block)
        self.testcase.assertTrue(connection.get_autocommit())
        self.events.append(name)

    def _read(self, offer_id, **kwargs):
        self.boundary('private_read', offer_id)
        self.testcase.assertTrue(kwargs.get('renewal_safe'))
        item = self.private_responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def _credentials(self, offer_id, **kwargs):
        self.boundary('credential_read', offer_id)
        self.testcase.assertTrue(kwargs.get('renewal_safe'))
        # The pending attempt must have committed even before credential reads.
        self.testcase.assertEqual(Check.objects.get().outcome, 'pending')
        return self.credentials

    def _update(self, offer_id, payload, **kwargs):
        self.boundary('one_shot_update', offer_id)
        claim = Check.objects.get()
        self.testcase.assertEqual(claim.outcome, 'pending')
        self.testcase.assertIsNotNone(claim.cycle_key)
        self.testcase.assertIsNotNone(claim.unresolved_key)
        self.testcase.assertEqual(payload['details']['offerTitle'], 'Authoritative live title')
        self.testcase.assertEqual(payload['details']['description'], '')
        self.testcase.assertEqual(payload['details']['mainOfferImage'], {})
        self.testcase.assertEqual(payload['accountDeliveryDetails'], [DETAIL])
        return SimpleNamespace(ok=True, error=None)


class EldoradoRenewalSafetyTests(TransactionTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.expiry = self.now + timedelta(hours=72)
        self.verified = self.now + timedelta(days=21)
        self.account = IntegrationAccount.objects.create(
            name='Synthetic Eldorado', slug='synthetic-eldorado', provider='eldorado', role='sell')
        self.credential = IntegrationCredential.objects.create(account=self.account, credentials={'synthetic': True})
        self.listing = self.make_listing()
        self.flag = SyncFeatureFlag.objects.create(key=SyncFlag.RENEW_EXPIRING_LISTINGS,
            is_enabled=True, value={'providers': ['eldorado']})
        self.client = FakeLeasedClient(self, self.expiry, self.verified)

    def make_listing(self, *, offer_id=OID, account=None):
        return Listing.objects.create(integration_account=account or self.account,
            store_listing_id=offer_id, status='paused', title='Stale local title', price='99.00',
            marketplace_expires_at=self.expiry,
            raw_data={'description': 'stale description', 'mainOfferImage': {'stale': True}})

    def renew(self, **kwargs):
        args = dict(now=self.now, cutoff=self.now + timedelta(hours=96), execute=True,
                    client_for=lambda listing: self.client, sleep=lambda seconds: None)
        args.update(kwargs)
        return R.renew_eldorado_listing(self.listing, **args)

    def hold(self, *, outcome='unknown', listing=None, expiry=None):
        listing = listing or self.listing
        expiry = expiry or self.expiry
        return Check.objects.create(listing=listing, integration_account=listing.integration_account,
            provider='eldorado', offer_id=OID,
            cycle_key=R.renewal_cycle_key(listing.integration_account_id, OID, expiry),
            unresolved_key=(R.unresolved_offer_key(listing.integration_account_id, OID)
                            if outcome in R.UNRESOLVED_OUTCOMES else None),
            outcome=outcome, reason_code='attempt_pending', previous_expires_at=expiry)

    def assert_no_send(self, decision):
        self.assertEqual(decision.writes_attempted, 0)
        self.client.update_offer_once.assert_not_called()
        self.client.update_offer.assert_not_called()

    def order(self, **changes):
        values = dict(integration_account=self.account, store_order_id='synthetic-order',
                      store_listing_id=OID, price='10.00', status='pending')
        values.update(changes)
        # Avoid unrelated order lifecycle signals; only local evidence is tested.
        return Order.objects.bulk_create([Order(**values)])[0]

    def test_default_path_commits_pending_and_keeps_one_lease_through_verification(self):
        decision = self.renew(read_budget=3)
        self.assertEqual((decision.outcome, decision.writes_attempted, decision.reads_used), ('renewed', 1, 3))
        self.assertEqual(self.client.events, ['lease_enter', 'private_read', 'credential_read',
                                             'one_shot_update', 'private_read', 'lease_exit'])
        self.client.update_offer.assert_not_called()
        self.client.update_offer_once.assert_called_once()
        claim = Check.objects.get()
        self.assertEqual(claim.outcome, 'renewed')
        self.assertEqual(claim.reason_code, 'verified_expiry_extended')
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, 'listed')
        self.assertEqual(self.listing.marketplace_expires_at, self.verified)
        self.assertEqual(self.listing.title, 'Stale local title')
        self.assertEqual(self.listing.raw_data['description'], 'stale description')

    def test_disabled_or_missing_unified_flag_refuses_before_client_or_read(self):
        self.flag.delete()
        builder = Mock(side_effect=AssertionError('client must not be built'))
        decision = self.renew(client_for=builder)
        self.assertEqual(decision.reason, 'renewal_disabled')
        self.assert_no_send(decision)
        builder.assert_not_called()
        self.client.get_private_offer.assert_not_called()

    def test_pa_legacy_flag_never_authorizes_eldorado(self):
        self.flag.delete()
        SyncFeatureFlag.objects.create(key=SyncFlag.RENEW_EXPIRING_PA, is_enabled=True)
        self.assertEqual(self.renew().reason, 'renewal_disabled')
        self.client.get_private_offer.assert_not_called()

    def test_unified_scope_excluding_eldorado_refuses(self):
        self.flag.value = {'providers': ['playerauctions']}
        self.flag.save(update_fields=['value'])
        self.assertEqual(self.renew().reason, 'renewal_disabled')
        self.client.get_private_offer.assert_not_called()

    def test_feature_lookup_exception_fails_closed(self):
        with patch('apps.sync.services.shared.feature_flags.unified_renewal_providers', side_effect=RuntimeError('private-error-sentinel')):
            decision = self.renew()
        self.assertEqual(decision.reason, 'renewal_disabled')
        self.assert_no_send(decision)

    def test_caller_transaction_is_refused_before_transport(self):
        with transaction.atomic():
            decision = self.renew()
        self.assertEqual((decision.reason, decision.stop_run), ('transaction_active', True))
        self.assert_no_send(decision)
        self.client.get_private_offer.assert_not_called()
        self.assertFalse(Check.objects.exists())

    def test_missing_lease_refuses_without_private_read(self):
        self.client.offer_mutation = None
        decision = self.renew()
        self.assertEqual(decision.reason, 'serialization_unavailable')
        self.assert_no_send(decision)
        self.client.get_private_offer.assert_not_called()

    def test_denied_lease_refuses_without_private_read(self):
        self.client.admitted = False
        decision = self.renew()
        self.assertEqual(decision.reason, 'mutation_not_admitted')
        self.assert_no_send(decision)
        self.client.get_private_offer.assert_not_called()

    def test_missing_one_shot_method_never_falls_back_to_editor_or_retry(self):
        self.client.update_offer_once = None
        decision = self.renew()
        self.assertEqual(decision.reason, 'one_shot_update_unavailable')
        self.assertEqual(decision.writes_attempted, 0)
        self.client.update_offer.assert_not_called()
        self.client.get_private_offer.assert_not_called()

    def test_missing_or_inactive_configuration_refuses_even_with_injected_client(self):
        self.credential.is_active = False
        self.credential.save(update_fields=['is_active'])
        decision = self.renew()
        self.assert_no_send(decision)
        self.client.get_private_offer.assert_not_called()

    def test_missing_payload_configuration_is_proven_local_no_send(self):
        with patch('apps.integrations.proxy_pool.get_group_name', side_effect=RuntimeError('private-error-sentinel')):
            decision = self.renew()
        self.assertEqual((decision.reason, decision.outcome), ('save_configuration_missing', 'failed'))
        self.assert_no_send(decision)
        self.assertEqual(decision.reads_used, 1)
        self.assertEqual(Check.objects.get().reason_code, 'save_configuration_missing')

    def test_pending_unknown_and_unproven_never_age_out_or_change_cycle(self):
        for outcome in R.UNRESOLVED_OUTCOMES:
            with self.subTest(outcome=outcome):
                Check.objects.all().delete()
                claim = self.hold(outcome=outcome)
                Check.objects.filter(pk=claim.pk).update(created_at=self.now - timedelta(days=365))
                Listing.objects.filter(pk=self.listing.pk).update(marketplace_expires_at=self.verified)
                decision = self.renew(now=self.now + timedelta(days=400), cutoff=self.now + timedelta(days=404))
                self.assertEqual((decision.reason, decision.stop_run), ('unresolved_attempt', True))
                self.assert_no_send(decision)
                self.assertIn(self.listing.pk, R.recently_checked_ids(self.now + timedelta(days=400)))
        self.client.get_private_offer.assert_not_called()

    def test_same_account_offer_alias_cannot_escape_old_pending_listing(self):
        original = self.listing
        self.hold(listing=original)
        Listing.objects.filter(pk=original.pk).update(store_listing_id='different-current-offer')
        self.listing = self.make_listing(offer_id=OID.upper())
        decision = self.renew()
        self.assertEqual(decision.reason, 'unresolved_attempt')
        self.assert_no_send(decision)
        self.assertIn(self.listing.pk, R.recently_checked_ids(self.now))
        self.client.get_private_offer.assert_not_called()

    def test_another_account_same_offer_does_not_share_hold(self):
        other = IntegrationAccount.objects.create(name='Other synthetic', slug='other-synthetic', provider='eldorado')
        IntegrationCredential.objects.create(account=other, credentials={'synthetic': True})
        held_listing = self.make_listing(account=other)
        self.hold(listing=held_listing)
        # Test account scoping before save; no delivery/mock ledger ambiguity.
        self.assertFalse(R._unresolved(self.listing))
        self.assertTrue(R._unresolved(held_listing))

    def test_exact_cycle_cannot_replay_even_after_success(self):
        self.hold(outcome='renewed')
        decision = self.renew()
        self.assertEqual(decision.reason, 'cycle_already_checked')
        self.assert_no_send(decision)
        self.client.get_offer_account_details.assert_not_called()

    def test_cycle_key_is_full_utc_expiry_and_account_offer_identity(self):
        key = R.renewal_cycle_key(self.account.pk, OID.upper(), self.expiry)
        self.assertEqual(key, R.renewal_cycle_key(self.account.pk, OID, self.expiry))
        self.assertNotEqual(key, R.renewal_cycle_key(self.account.pk, OID, self.expiry + timedelta(microseconds=1)))
        self.assertNotEqual(key, R.renewal_cycle_key(self.account.pk + 1, OID, self.expiry))
        self.assertEqual(len(key), 64)

    def test_database_uniqueness_blocks_cycle_and_changed_cycle_unresolved_alias(self):
        self.hold()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.hold(outcome='renewed')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.hold(outcome='pending', expiry=self.expiry + timedelta(days=1))
        self.assertEqual(Check.objects.count(), 1)

    def test_unresolved_key_retains_unknown_and_releases_only_verified_terminal_claim(self):
        self.client.update_offer_once.side_effect = RuntimeError('synthetic-response-loss')
        self.renew()
        self.assertEqual(Check.objects.get().unresolved_key, R.unresolved_offer_key(self.account.pk, OID))
        Check.objects.all().delete()  # synthetic fixture only, never an admin action
        self.client = FakeLeasedClient(self, self.expiry, self.verified)
        self.assertEqual(self.renew().outcome, 'renewed')
        claim = Check.objects.get()
        self.assertIsNone(claim.unresolved_key)
        self.assertIsNotNone(claim.cycle_key)

    def test_proven_credential_read_refusal_clears_portable_slot_without_any_send(self):
        self.client.credentials = SimpleNamespace(ok=False, error='synthetic-read-failure')
        decision = self.renew()
        self.assert_no_send(decision)
        self.assertEqual(Check.objects.get().outcome, 'failed')
        self.assertIsNone(Check.objects.get().unresolved_key)

    def test_attempt_preserves_listing_and_account_on_delete(self):
        self.hold(outcome='pending')
        with self.assertRaises(ProtectedError):
            self.listing.delete()
        with self.assertRaises(ProtectedError):
            self.account.delete()
        self.assertEqual(Check.objects.count(), 1)

    def test_claim_creation_failure_never_transports_credentials_or_update(self):
        with patch.object(Check.objects, 'create', side_effect=RuntimeError('private-claim-sentinel')):
            # Service uses .using(db), so patch the QuerySet implementation too.
            with patch('django.db.models.query.QuerySet.create', side_effect=RuntimeError('private-claim-sentinel')):
                decision = self.renew()
        self.assert_no_send(decision)
        self.assertTrue(decision.stop_run)
        self.client.get_offer_account_details.assert_not_called()
        self.assertFalse(Check.objects.exists())
        self.assertNotIn('private-', decision.reason)

    def test_process_crash_after_send_leaves_committed_pending_and_blocks_replay(self):
        class SimulatedCrash(BaseException):
            pass
        def crash(offer_id, payload, **kwargs):
            self.client.boundary('one_shot_update', offer_id)
            self.assertEqual(Check.objects.get().outcome, 'pending')
            raise SimulatedCrash()
        self.client.update_offer_once.side_effect = crash
        with self.assertRaises(SimulatedCrash):
            self.renew()
        self.assertEqual(Check.objects.get().outcome, 'pending')
        decision = self.renew()
        self.assertEqual(decision.reason, 'unresolved_attempt')
        self.assertEqual(self.client.update_offer_once.call_count, 1)
        self.assertEqual(self.client.lease_depth, 0)

    def test_finalization_exception_leaves_pending_and_accounts_for_possible_write(self):
        with patch.object(R, '_finalize', side_effect=RuntimeError('private-finalize-sentinel')):
            decision = self.renew()
        self.assertEqual((decision.outcome, decision.reason, decision.writes_attempted), ('unknown', 'ledger_unavailable', 1))
        self.assertTrue(decision.stop_run)
        self.assertEqual(Check.objects.get().outcome, 'pending')

    def test_failed_sends_never_trust_provider_no_write_labels_or_store_error_text(self):
        error = SimpleNamespace(details={'no_write': True, 'governor': 'writes_held'}, message='private-credential-sentinel')
        self.client.update_offer_once.side_effect = lambda *args, **kwargs: SimpleNamespace(ok=False, error=error)
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.reason, decision.writes_attempted), ('unknown', 'send_failed_unknown', 1))
        self.assertTrue(decision.stop_run)
        claim = Check.objects.get()
        self.assertEqual(claim.outcome, 'unknown')
        self.assertEqual(claim.reason_code, 'send_failed_unknown')
        self.assertNotIn('sentinel', claim.reason_code)

    def test_raised_send_error_is_unknown_and_sanitized(self):
        self.client.update_offer_once.side_effect = RuntimeError('private-payload-sentinel')
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.writes_attempted), ('unknown', 1))
        self.assertTrue(decision.stop_run)
        self.assertEqual(Check.objects.get().reason_code, 'attempt_exception')

    def test_injected_save_exception_cannot_claim_controlled_local_no_write(self):
        def injected_save(listing, live, client):
            self.assertIs(client, self.client)
            raise R._LocalPreSendRefusal('payload_invalid')
        decision = self.renew(save=injected_save)
        self.assertEqual((decision.outcome, decision.writes_attempted), ('unknown', 1))
        self.assertTrue(decision.stop_run)
        self.assertEqual(Check.objects.get().outcome, 'unknown')

    def test_raised_verify_error_is_unknown_and_stops_run(self):
        self.client.private_responses[1] = RuntimeError('private-response-sentinel')
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.writes_attempted, decision.reads_used), ('unknown', 1, 3))
        self.assertTrue(decision.stop_run)
        self.assertEqual(Check.objects.get().outcome, 'unknown')
        self.assertNotIn('sentinel', Check.objects.get().reason_code)

    def test_unproven_verification_creates_indefinite_hold(self):
        self.client.private_responses[1] = response(snapshot(self.expiry))
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.stop_run, decision.writes_attempted), ('unproven', True, 1))
        self.assertEqual(Check.objects.get().outcome, 'unproven')
        self.assertEqual(self.renew().reason, 'unresolved_attempt')
        self.assertEqual(self.client.update_offer_once.call_count, 1)

    def test_local_order_any_status_holds_before_claim(self):
        self.order(status='cancelled')
        decision = self.renew()
        self.assertEqual(decision.outcome, 'held_sale')
        self.assert_no_send(decision)
        self.assertIsNone(Check.objects.get().cycle_key)

    def test_direct_linked_order_without_remote_offer_identity_holds(self):
        self.order(listing=self.listing, integration_account=None, store_listing_id='')
        self.assertEqual(self.renew().outcome, 'held_sale')
        self.client.update_offer_once.assert_not_called()

    def test_sale_created_during_content_read_is_held_by_fresh_guard(self):
        original = self.client._read
        def read_with_sale(offer_id, **kwargs):
            read = original(offer_id, **kwargs)
            PoolSaleEvent.objects.create(event_key='synthetic-sale', listing=self.listing)
            return read
        self.client.get_private_offer.side_effect = read_with_sale
        decision = self.renew()
        self.assertEqual(decision.outcome, 'held_sale')
        self.assert_no_send(decision)
        self.client.get_offer_account_details.assert_not_called()

    def test_sale_during_credentials_is_rechecked_before_send(self):
        original = self.client._credentials
        def read_with_sale(offer_id, **kwargs):
            data = original(offer_id, **kwargs)
            self.order()
            return data
        self.client.get_offer_account_details.side_effect = read_with_sale
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.reason), ('held_sale', 'local_sale_or_order'))
        self.assert_no_send(decision)
        self.assertEqual(Check.objects.get().outcome, 'held_sale')

    def test_sale_arriving_between_initial_guard_and_claim_is_held(self):
        original = R._claim
        def claim_with_sale(listing, previous):
            self.order()
            return original(listing, previous)
        with patch.object(R, '_claim', side_effect=claim_with_sale):
            decision = self.renew()
        self.assertEqual(decision.outcome, 'held_sale')
        self.assert_no_send(decision)
        self.client.get_offer_account_details.assert_not_called()
        self.assertFalse(Check.objects.filter(cycle_key__isnull=False).exists())

    def test_reassignment_during_credentials_never_updates_wrong_offer(self):
        original = self.client._credentials
        def reassign(offer_id, **kwargs):
            data = original(offer_id, **kwargs)
            Listing.objects.filter(pk=self.listing.pk).update(store_listing_id='another-offer')
            return data
        self.client.get_offer_account_details.side_effect = reassign
        decision = self.renew()
        self.assertEqual(decision.reason, 'listing_changed')
        self.assert_no_send(decision)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.store_listing_id, 'another-offer')

    def test_local_status_change_during_content_read_is_refreshed(self):
        original = self.client._read
        def close_listing(offer_id, **kwargs):
            data = original(offer_id, **kwargs)
            Listing.objects.filter(pk=self.listing.pk).update(status='closed')
            return data
        self.client.get_private_offer.side_effect = close_listing
        decision = self.renew()
        self.assertEqual(decision.reason, 'listing_changed')
        self.assert_no_send(decision)

    def test_sale_after_send_prevents_revive_and_holds_outcome_unknown(self):
        original = self.client._update
        def update_with_sale(offer_id, payload, **kwargs):
            saved = original(offer_id, payload, **kwargs)
            self.order()
            return saved
        self.client.update_offer_once.side_effect = update_with_sale
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.reason, decision.writes_attempted), ('unknown', 'local_state_changed_after_send', 1))
        self.assertTrue(decision.stop_run)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, 'paused')
        self.assertEqual(self.listing.marketplace_expires_at, self.expiry)

    def test_finalization_never_rewrites_a_reassigned_listing(self):
        original = self.client._update
        def update_with_reassignment(offer_id, payload, **kwargs):
            saved = original(offer_id, payload, **kwargs)
            Listing.objects.filter(pk=self.listing.pk).update(store_listing_id='new-local-identity')
            return saved
        self.client.update_offer_once.side_effect = update_with_reassignment
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.reason), ('unknown', 'local_state_changed_after_send'))
        self.assertEqual(Check.objects.get().offer_id, OID)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.store_listing_id, 'new-local-identity')
        self.assertEqual(self.listing.marketplace_expires_at, self.expiry)

    def test_credential_failure_is_proven_no_send_with_fixed_reason(self):
        self.client.credentials = SimpleNamespace(ok=False, error='private-error-sentinel')
        decision = self.renew()
        self.assertEqual((decision.outcome, decision.reason, decision.reads_used), ('failed', 'credential_read_failed', 2))
        self.assert_no_send(decision)
        self.assertEqual(Check.objects.get().reason_code, 'credential_read_failed')

    def test_missing_live_field_is_not_filled_from_model_or_local_snapshot(self):
        current = snapshot(self.expiry)
        del current['offerTitle']
        self.client.private_responses[0] = response(current)
        decision = self.renew()
        self.assertEqual(decision.reason, 'payload_invalid')
        self.assert_no_send(decision)
        self.assertEqual(Check.objects.get().outcome, 'failed')

    def test_lossy_and_unknown_public_values_are_refused_after_actual_private_model_parsing(self):
        cases = [
            snapshot(self.expiry, quantity=True),
            snapshot(self.expiry, pricePerUnit={'amount': 9007199254740993, 'currency': 'USD'}),
            snapshot(self.expiry, pricePerUnit={'amount': 12.5, 'currency': 'USD', 'unknownEditableField': 'synthetic'}),
            snapshot(self.expiry, mainOfferImage={'smallImage': 's', 'largeImage': 'l', 'originalSizeImage': 'o', 'unknownEditableField': 'synthetic'}),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                Check.objects.all().delete()
                self.client = FakeLeasedClient(self, self.expiry, self.verified)
                self.client.private_responses[0] = response(raw)
                decision = self.renew()
                self.assertEqual(decision.reason, 'payload_invalid')
                self.assert_no_send(decision)

    def test_read_budget_zero_or_insufficient_never_sends(self):
        decision = self.renew(read_budget=0)
        self.assertEqual((decision.reason, decision.reads_used), ('read_budget_exhausted', 0))
        self.assert_no_send(decision)
        self.client.get_private_offer.assert_not_called()
        decision = self.renew(read_budget=2)
        self.assertEqual((decision.reason, decision.reads_used), ('read_budget_exhausted', 1))
        self.assert_no_send(decision)
        self.client.get_offer_account_details.assert_not_called()
        self.assertFalse(Check.objects.filter(cycle_key__isnull=False).exists())

    def test_dry_run_uses_lease_but_never_claims_or_sends(self):
        self.flag.delete()
        decision = self.renew(execute=False, read_budget=1)
        self.assertEqual((decision.reason, decision.reads_used), ('dry_run_would_renew', 1))
        self.assert_no_send(decision)
        self.assertFalse(Check.objects.exists())

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_exact_claims_admit_only_one_committed_attempt(self):
        barrier = threading.Barrier(2)
        results = []
        errors = []
        def worker():
            close_old_connections()
            try:
                listing = Listing.objects.get(pk=self.listing.pk)
                barrier.wait(timeout=10)
                attempt, decision = R._claim(listing, self.expiry)
                results.append((attempt is not None, decision.reason if decision else 'claimed'))
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                close_old_connections()
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum(claimed for claimed, reason in results), 1)
        self.assertEqual(Check.objects.filter(outcome='pending').count(), 1)


class EldoradoVerificationSafetyTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()

    def verify(self, previous, after):
        return R.decide_after_save(previous=previous, after_ok=True,
                                   after=after, offer_id=OID, now=self.now)

    def test_later_but_still_past_and_excessive_future_expiry_are_unproven(self):
        previous = self.now - timedelta(days=5)
        for expiry in (self.now - timedelta(days=4), self.now,
                       self.now + timedelta(days=61)):
            with self.subTest(expiry=expiry):
                decision = self.verify(previous, snapshot(expiry))
                self.assertEqual((decision.outcome, decision.stop_run), ('unproven', True))

    def test_missing_previous_expiry_never_proves_extension(self):
        decision = self.verify(None, snapshot(self.now + timedelta(days=21)))
        self.assertEqual(decision.outcome, 'unproven')

    def test_sdk_defaults_do_not_create_authoritative_live_keys(self):
        data = response({'id': OID, 'offerState': 'Active', 'expireDate': self.now.isoformat(),
                         'description': None, 'mainOfferImage': None})
        live = R._live_dict(data)
        self.assertNotIn('offerTitle', live)
        self.assertNotIn('quantity', live)
        self.assertIsNone(live['description'])
        self.assertIsNone(live['mainOfferImage'])

    def test_remote_state_text_is_fixed_code_not_audit_text(self):
        decision = R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200,
            live=snapshot(self.now, offerState='private-credential-sentinel'),
            now=self.now, cutoff=self.now + timedelta(days=4))
        self.assertEqual(decision.reason, 'remote_not_active')

    def test_migration_is_schema_only_without_cached_expiry_backfill(self):
        migration = importlib.import_module('apps.sync.migrations.0013_marketplace_renewal_check')
        self.assertEqual(len(migration.Migration.operations), 1)
        self.assertEqual(type(migration.Migration.operations[0]).__name__, 'CreateModel')
        self.assertFalse(hasattr(migration, 'backfill_eldorado_expiry'))

    def test_unresolved_slot_is_unconditionally_unique_not_partial(self):
        field = Check._meta.get_field('unresolved_key')
        self.assertTrue(field.unique)
        self.assertTrue(field.null)
        self.assertEqual(Check._meta.constraints, [])

    def test_raw_public_evidence_is_private_transient_and_not_added_to_model_dumps(self):
        raw = snapshot(self.now, pricePerUnit={
            'amount': 12.5, 'currency': 'USD', 'unknownEditableField': 'SYNTHETIC_RAW_SENTINEL',
        })
        model = EldoradoPrivateOffer.model_validate({'offer': raw})
        self.assertEqual(R._live_dict(SimpleNamespace(data=model)), raw)
        self.assertNotIn('_raw_offer_snapshot', model.model_dump())
        self.assertNotIn('SYNTHETIC_RAW_SENTINEL', repr(model))
        copied = model.raw_offer_snapshot()
        copied['pricePerUnit']['amount'] = 0
        self.assertEqual(model.raw_offer_snapshot()['pricePerUnit']['amount'], 12.5)
