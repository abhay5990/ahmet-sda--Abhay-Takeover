"""Unified auto-renewal: Eldorado renewer decisions, gating and run safety (no DB)."""
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.sync.services.eldorado import renewal as R

NOW = datetime(2026, 11, 5, 17, 0, tzinfo=dt_timezone.utc)
CUTOFF = NOW + timedelta(hours=96)
OID = '3d952183-48cb-476e-ab3f-08df24631e7b'


def live(state='Active', expire='2026-11-08T18:00:00', oid=OID, **extra):
    return {'id': oid, 'offerState': state, 'expireDate': expire, **extra}


def result(ok=True, offer=None, status=200, category=''):
    data = SimpleNamespace(offer=SimpleNamespace(model_dump=lambda: dict(offer or {}), model_extra={})) if ok else None
    error = None if ok else SimpleNamespace(category=category, status_code=status)
    return SimpleNamespace(ok=ok, data=data, status_code=status, error=error)


class DecisionTests(SimpleTestCase):
    def test_parse_expire_date_is_utc(self):
        self.assertEqual(R.parse_expire_date('2026-11-26T18:00:00'), datetime(2026, 11, 26, 18, tzinfo=dt_timezone.utc))
        self.assertIsNone(R.parse_expire_date('soon'))

    def test_not_found_is_gone_and_other_read_errors_fail(self):
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=False, read_status=404, live=None, now=NOW, cutoff=CUTOFF).outcome, 'gone')
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=False, read_status=500, live=None, now=NOW, cutoff=CUTOFF).outcome, 'failed')
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=False, read_status=None, live=None, now=NOW, cutoff=CUTOFF).reason, 'read_failed')

    def test_wrong_offer_or_inactive_is_never_saved(self):
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(oid='other'), now=NOW, cutoff=CUTOFF).reason, 'identity_mismatch')
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(state='Paused'), now=NOW, cutoff=CUTOFF).outcome, 'not_active')
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(state='Closed'), now=NOW, cutoff=CUTOFF).outcome, 'not_active')

    def test_due_vs_not_due(self):
        self.assertIsNone(R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(expire='2026-11-08T18:00:00'), now=NOW, cutoff=CUTOFF))
        self.assertIsNone(R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(expire='2026-11-01T18:00:00'), now=NOW, cutoff=CUTOFF))
        far = R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(expire='2026-11-26T18:00:00'), now=NOW, cutoff=CUTOFF)
        self.assertEqual((far.outcome, far.verified), ('not_due', datetime(2026, 11, 26, 18, tzinfo=dt_timezone.utc)))
        self.assertEqual(R.decide_from_live_offer(offer_id=OID, read_ok=True, read_status=200, live=live(expire=None), now=NOW, cutoff=CUTOFF).reason, 'expiry_unreadable')

    def test_renewed_only_when_a_fresh_read_shows_a_later_expiry(self):
        prev = R.parse_expire_date('2026-11-08T18:00:00')
        ok = R.decide_after_save(previous=prev, after_ok=True, after=live(expire='2026-11-26T18:00:00'), offer_id=OID, now=NOW)
        self.assertEqual((ok.outcome, ok.stop_run), ('renewed', False))
        same = R.decide_after_save(previous=prev, after_ok=True, after=live(expire='2026-11-08T18:00:00'), offer_id=OID, now=NOW)
        self.assertEqual((same.outcome, same.stop_run), ('unproven', True))
        self.assertTrue(R.decide_after_save(previous=prev, after_ok=False, after=None, offer_id=OID, now=NOW).stop_run)
        self.assertEqual(R.decide_after_save(previous=prev, after_ok=True, after=live(state='Paused', expire='2026-11-26T18:00:00'), offer_id=OID, now=NOW).reason, 'verify_state_changed')


# Real committed claims require TransactionTestCase, not TestCase savepoints.
from contextlib import contextmanager
from django.test import TransactionTestCase


class RenewListingTests(TransactionTestCase):
    def setUp(self):
        from apps.integrations.models import IntegrationAccount, IntegrationCredential
        from apps.listings.models import Listing
        from apps.sync.models import SyncFeatureFlag
        from apps.sync.services.shared.feature_flags import SyncFlag
        account = IntegrationAccount.objects.create(name='Synthetic Eldorado', slug='synthetic-eldorado', provider='eldorado')
        IntegrationCredential.objects.create(account=account, credentials={'synthetic': True})
        self.listing = Listing.objects.create(integration_account=account, store_listing_id=OID, status='listed', price='10.00')
        SyncFeatureFlag.objects.update_or_create(key=SyncFlag.RENEW_EXPIRING_LISTINGS,
            defaults={'is_enabled': True, 'value': {'providers': ['eldorado']}})
        store = patch.object(R, '_store_expiry'); self.store = store.start(); self.addCleanup(store.stop)
        guard = patch.object(R, '_has_sale_or_open_order', return_value=False); self.guard = guard.start(); self.addCleanup(guard.stop)

    def run_once(self, reads, save_ok=True, execute=True):
        # The original response factory predates exclude_unset=True. Preserve
        # explicit fixture fields as dicts rather than synthesizing defaults.
        for read in reads:
            if read.ok:
                read.data.offer = read.data.offer.model_dump()
        leased = []
        @contextmanager
        def mutation(offer_id):
            self.assertEqual(offer_id, OID)
            leased.append(True)
            try:
                yield True
            finally:
                leased.pop()
        client = Mock()
        client.offer_mutation = mutation
        def read_offer(offer_id, **kwargs):
            self.assertTrue(leased)
            self.assertTrue(kwargs.get('renewal_safe'))
            return reads.pop(0)
        client.get_private_offer.side_effect = read_offer
        save = Mock(return_value=SimpleNamespace(ok=save_ok, error=None if save_ok else 'Eldorado offer mutation busy or writes held'))
        d = R.renew_eldorado_listing(self.listing, now=NOW, cutoff=CUTOFF, execute=execute, client_for=lambda l: client, save=save, sleep=lambda s: None)
        if save.called:
            self.assertIs(save.call_args.args[2], client)
        return d, client, save

    def test_due_offer_is_saved_unchanged_and_verified(self):
        d, client, save = self.run_once([result(offer=live()), result(offer=live(expire='2026-11-26T18:00:00'))])
        self.assertEqual(d.outcome, 'renewed'); save.assert_called_once(); self.assertEqual(client.get_private_offer.call_count, 2)
        self.store.assert_called_once()

    def test_dry_run_never_saves(self):
        d, _, save = self.run_once([result(offer=live())], execute=False)
        from apps.sync.models import MarketplaceRenewalCheck
        self.assertEqual(d.reason, 'dry_run_would_renew'); save.assert_not_called()
        self.assertFalse(MarketplaceRenewalCheck.objects.exists())

    def test_sale_evidence_holds_before_any_save(self):
        self.guard.return_value = True
        d, _, save = self.run_once([result(offer=live())])
        self.assertEqual(d.outcome, 'held_sale'); save.assert_not_called()

    def test_not_due_and_gone_never_save(self):
        d, _, save = self.run_once([result(offer=live(expire='2026-11-26T18:00:00'))])
        self.assertEqual(d.outcome, 'not_due'); save.assert_not_called(); self.store.assert_called_once()
        d, _, save = self.run_once([result(ok=False, status=404)])
        self.assertEqual(d.outcome, 'gone'); save.assert_not_called()

    def test_busy_or_held_save_stops_the_run(self):
        d, _, _ = self.run_once([result(offer=live())], save_ok=False)
        self.assertEqual((d.outcome, d.stop_run, d.writes_attempted), ('unknown', True, 1))

    def test_unproven_save_stops_the_run(self):
        d, _, _ = self.run_once([result(offer=live()), result(offer=live())])
        self.assertEqual((d.outcome, d.stop_run), ('unproven', True))


class CommandGateTests(SimpleTestCase):
    def test_execute_is_refused_while_the_switch_is_off(self):
        with patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers', return_value=()):
            with self.assertRaises(CommandError):
                call_command('renew_expiring_listings', '--execute', stdout=StringIO())

    def test_execute_refuses_a_provider_the_switch_does_not_cover(self):
        with patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers', return_value=('playerauctions',)):
            with self.assertRaises(CommandError):
                call_command('renew_expiring_listings', '--execute', '--providers', 'eldorado', stdout=StringIO())

    def test_eldorado_run_stops_at_the_first_unproven_save(self):
        listings = [SimpleNamespace(store_listing_id=f'id-{i}') for i in range(3)]
        decisions = [R.RenewalDecision('renewed', 'verified_expiry_extended', NOW, NOW + timedelta(days=21)),
                     R.RenewalDecision('unproven', 'saved_but_expiry_unchanged', NOW, NOW, stop_run=True),
                     R.RenewalDecision('renewed', 'verified_expiry_extended', NOW, NOW)]
        out = StringIO()
        with patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers', return_value=('eldorado',)), \
             patch.object(R, 'eldorado_candidates', return_value=listings), \
             patch.object(R, 'renew_eldorado_listing', side_effect=decisions) as renew:
            call_command('renew_expiring_listings', '--execute', '--providers', 'eldorado', stdout=out)
        self.assertEqual(renew.call_count, 2)
        self.assertIn('STOPPED (unproven:saved_but_expiry_unchanged)', out.getvalue())

    def test_scheduler_uses_unified_switch_then_falls_back_to_pa_only(self):
        from apps.sync.management.commands.runapscheduler import run_renew_expiring_playerauctions_job
        with patch('apps.sync.services.shared.feature_flags.unified_renewal_providers', return_value=('playerauctions', 'eldorado')), \
             patch('django.core.management.call_command') as dispatch:
            run_renew_expiring_playerauctions_job()
        dispatch.assert_called_once_with('renew_expiring_listings', '--execute')


class PauseSkipTests(SimpleTestCase):
    def test_db_only_pause_skips_eldorado_while_auto_renewal_covers_it(self):
        out = StringIO()
        with patch('apps.sync.services.shared.feature_flags.unified_renewal_providers', return_value=('eldorado',)), \
             patch('apps.sync.management.commands.pause_expiring_listings.Listing') as listing_model:
            call_command('pause_expiring_listings', '--execute', stdout=out)
        listing_model.objects.filter.assert_not_called()
        self.assertIn('skipped — auto-renewal is on', out.getvalue())
