"""Main-only PR47 safety regressions; synthetic database and mocked transport."""
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from apps.sync.models import SyncFeatureFlag
from apps.sync.services import pa_mart_renewal
from apps.sync.services.shared import feature_flags as flags
from apps.sync.management.commands.runapscheduler import run_renew_expiring_playerauctions_job


class UnifiedScopeTests(TestCase):
    def configure(self, value, enabled=True):
        return SyncFeatureFlag.objects.create(
            key=flags.SyncFlag.RENEW_EXPIRING_LISTINGS,
            is_enabled=enabled, value=value,
        )

    def test_unified_pa_only_admits_final_mart_helper_with_old_flag_false(self):
        SyncFeatureFlag.objects.create(key=flags.SyncFlag.RENEW_EXPIRING_PA, is_enabled=False)
        self.configure({'providers': ['playerauctions']})
        self.assertEqual(flags.unified_renewal_providers(), ('playerauctions',))
        self.assertTrue(pa_mart_renewal._enabled())
        with patch('django.core.management.call_command') as dispatch:
            run_renew_expiring_playerauctions_job()
        dispatch.assert_called_once_with('renew_expiring_listings', '--execute')
        # Command admission and final helper agree; the real empty candidate
        # query cannot create, renew or allocate anything in this synthetic DB.
        call_command('renew_expiring_playerauctions', '--execute', stdout=StringIO())

    def test_explicit_eldorado_only_never_admits_pa(self):
        self.configure({'providers': ['eldorado']})
        self.assertEqual(flags.unified_renewal_providers(), ('eldorado',))
        self.assertFalse(pa_mart_renewal._enabled())

    def test_disabled_missing_invalid_scope_refuses(self):
        self.assertEqual(flags.unified_renewal_providers(), ())
        for value in ({}, {'providers': []}, {'providers': 'eldorado'},
                      {'providers': ['eldorado', 'unknown']}, {'providers': [None]},
                      {'providers': ['ELDORADO']}, None):
            with self.subTest(value=value):
                row = self.configure(value)
                self.assertEqual(flags.unified_renewal_providers(), ())
                self.assertFalse(pa_mart_renewal._enabled())
                row.delete()
        self.configure({'providers': ['playerauctions', 'eldorado']}, enabled=False)
        self.assertEqual(flags.unified_renewal_providers(), ())

    def test_provider_subset_and_duplicates_do_not_expand_scope(self):
        self.configure({'providers': ['eldorado', 'eldorado']})
        self.assertEqual(flags.unified_renewal_providers(), ('eldorado',))

    def test_pa_legacy_true_keeps_its_previous_admission(self):
        SyncFeatureFlag.objects.create(key=flags.SyncFlag.RENEW_EXPIRING_PA, is_enabled=True)
        self.assertEqual(flags.unified_renewal_providers(), ())
        self.assertTrue(pa_mart_renewal._enabled())

    def test_one_atomic_row_read_covers_enablement_and_scope(self):
        self.configure({'providers': ['playerauctions']})
        with self.assertNumQueries(1):
            self.assertEqual(flags.unified_renewal_providers(), ('playerauctions',))


class UnifiedFailureTests(SimpleTestCase):
    def test_lookup_failure_does_not_enable_any_provider(self):
        with patch('apps.sync.models.SyncFeatureFlag.objects') as rows:
            rows.filter.side_effect = RuntimeError('synthetic configuration unavailable')
            self.assertEqual(flags.unified_renewal_providers(), ())
            with patch('django.core.management.call_command') as dispatch:
                run_renew_expiring_playerauctions_job()
            dispatch.assert_not_called()

    def test_unsupported_lead_window_refuses_before_any_provider(self):
        for lead in (0, -1, 97, 720):
            with self.subTest(lead=lead), patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers') as scope:
                with self.assertRaisesMessage(CommandError, '--lead-hours'):
                    call_command('renew_expiring_listings', '--execute', '--lead-hours', str(lead), stdout=StringIO())
                scope.assert_not_called()

    def test_direct_pa_command_refuses_unsupported_lead_before_listing_query(self):
        with patch('apps.sync.management.commands.renew_expiring_playerauctions.Listing.objects') as listings:
            with self.assertRaisesMessage(CommandError, '--lead-hours'):
                call_command('renew_expiring_playerauctions', '--execute', '--lead-hours', '720', stdout=StringIO())
        listings.filter.assert_not_called()

    def test_eldorado_ledger_admin_cannot_edit_or_resend_unresolved_attempts(self):
        from django.contrib import admin
        from apps.sync.models import MarketplaceRenewalCheck
        view = admin.site._registry[MarketplaceRenewalCheck]
        self.assertFalse(view.has_add_permission(None))
        self.assertFalse(view.has_change_permission(None))
        self.assertFalse(view.has_delete_permission(None))
        self.assertIsNone(view.actions)
        self.assertNotIn('raw_data', view.fields)

    def test_unclassified_exception_stops_without_exposing_provider_text(self):
        from apps.sync.services.eldorado import renewal
        offers = [SimpleNamespace(store_listing_id='fixture-a'), SimpleNamespace(store_listing_id='fixture-b')]
        out = StringIO()
        with patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers', return_value=('eldorado',)), \
             patch.object(renewal, 'eldorado_candidates', return_value=offers), \
             patch.object(renewal, 'renew_eldorado_listing', side_effect=RuntimeError('SYNTHETIC_PRIVATE_SENTINEL')) as run:
            call_command('renew_expiring_listings', '--execute', '--providers', 'eldorado', stdout=out)
        self.assertEqual(run.call_count, 1)
        self.assertIn('STOPPED', out.getvalue())
        self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL', out.getvalue())

    def test_explicit_send_count_enforces_the_limit_without_reason_matching(self):
        from apps.sync.services.eldorado import renewal
        offers = [SimpleNamespace(store_listing_id='fixture-a'), SimpleNamespace(store_listing_id='fixture-b')]
        decision = SimpleNamespace(outcome='not_due', reason='fixed_local_reason', previous=None,
                                   verified=None, stop_run=False, writes_attempted=1, reads_used=3)
        with patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers', return_value=('eldorado',)), \
             patch.object(renewal, 'eldorado_candidates', return_value=offers), \
             patch.object(renewal, 'renew_eldorado_listing', return_value=decision) as run:
            call_command('renew_expiring_listings', '--execute', '--providers', 'eldorado', '--eldorado-renewals', '1', stdout=StringIO())
        self.assertEqual(run.call_count, 1)

    def test_total_logical_read_budget_includes_delivery_and_verification(self):
        from apps.sync.services.eldorado import renewal
        offers = [SimpleNamespace(store_listing_id='fixture-a'), SimpleNamespace(store_listing_id='fixture-b')]
        decision = SimpleNamespace(outcome='not_due', reason='fixed_local_reason', previous=None,
                                   verified=None, stop_run=False, writes_attempted=0, reads_used=3)
        with patch('apps.sync.management.commands.renew_expiring_listings.unified_renewal_providers', return_value=('eldorado',)), \
             patch.object(renewal, 'eldorado_candidates', return_value=offers), \
             patch.object(renewal, 'renew_eldorado_listing', return_value=decision) as run:
            call_command('renew_expiring_listings', '--execute', '--providers', 'eldorado', '--eldorado-reads', '3', stdout=StringIO())
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs['read_budget'], 3)
