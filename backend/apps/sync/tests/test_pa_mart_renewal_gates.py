"""PA renewal is held on missing flags and read failures, before all transport."""
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.sync.management.commands.runapscheduler import run_renew_expiring_playerauctions_job


class RenewalHoldTests(SimpleTestCase):
    def test_scheduler_missing_flag_does_not_dispatch(self):
        with patch('apps.sync.models.SyncFeatureFlag.objects') as flags, patch('django.core.management.call_command') as dispatch:
            flags.filter.return_value.only.return_value.first.return_value = None
            run_renew_expiring_playerauctions_job()
        dispatch.assert_not_called()

    def test_scheduler_lookup_exception_does_not_dispatch(self):
        with patch('apps.sync.models.SyncFeatureFlag.objects') as flags, patch('django.core.management.call_command') as dispatch:
            flags.filter.side_effect = RuntimeError('synthetic DB failure')
            run_renew_expiring_playerauctions_job()
        dispatch.assert_not_called()

    def test_scheduler_false_flag_does_not_dispatch(self):
        with patch('apps.sync.models.SyncFeatureFlag.objects') as flags, patch('django.core.management.call_command') as dispatch:
            flags.filter.return_value.only.return_value.first.return_value = SimpleNamespace(is_enabled=False)
            run_renew_expiring_playerauctions_job()
        dispatch.assert_not_called()

    def test_scheduler_explicit_true_flag_admits_command(self):
        with patch('apps.sync.models.SyncFeatureFlag.objects') as flags, patch('django.core.management.call_command') as dispatch:
            flags.filter.return_value.only.return_value.first.return_value = SimpleNamespace(is_enabled=True)
            run_renew_expiring_playerauctions_job()
        dispatch.assert_called_once_with('renew_expiring_playerauctions', '--execute')

    def test_manual_execute_missing_flag_refuses_before_listing_query(self):
        cmd = 'apps.sync.management.commands.renew_expiring_playerauctions'
        with patch('apps.sync.models.SyncFeatureFlag.objects') as flags, patch(cmd + '.Listing.objects') as listings:
            flags.filter.return_value.only.return_value.first.return_value = None
            with self.assertRaisesMessage(CommandError, 'renewal is held'):
                call_command('renew_expiring_playerauctions', '--execute', stdout=StringIO())
        listings.filter.assert_not_called()

    def test_manual_execute_failed_flag_read_refuses_before_listing_query(self):
        cmd = 'apps.sync.management.commands.renew_expiring_playerauctions'
        with patch('apps.sync.models.SyncFeatureFlag.objects') as flags, patch(cmd + '.Listing.objects') as listings:
            flags.filter.side_effect = RuntimeError('synthetic DB failure')
            with self.assertRaisesMessage(CommandError, 'renewal is held'):
                call_command('renew_expiring_playerauctions', '--execute', stdout=StringIO())
        listings.filter.assert_not_called()


class RenewalLocalInputTests(SimpleTestCase):
    def delegation_client(self):
        from apps.integrations.providers.playerauctions import MctMartDelegationClient
        client = MctMartDelegationClient.__new__(MctMartDelegationClient)
        client._delegate = Mock()
        return client

    def test_unsafe_request_ids_refused_without_transport(self):
        for request_id in ('', 'short', 'x' * 129, 'secret\nrequest-id', 'nonascii-\u2603-request-id', None):
            with self.subTest(request_id=request_id):
                client = self.delegation_client()
                result = client.renew_offer('900001001', request_id=request_id)
                self.assertFalse(result.ok)
                self.assertFalse(result.error.is_retryable)
                self.assertEqual(result.error.details['error_code'], 'renew_invalid_request_id')
                self.assertTrue(result.error.details['no_write_proof'])
                client._delegate.assert_not_called()

    def test_safe_request_id_preserved_exactly(self):
        client = self.delegation_client()
        client.renew_offer('900001001', request_id='sda-renew-900001001-synthetic-cycle')
        client._delegate.assert_called_once_with('renew', {'offerId': '900001001'}, request_id='sda-renew-900001001-synthetic-cycle')


class RenewalLedgerAdminTests(SimpleTestCase):
    def test_ledger_admin_has_no_mutation_or_retry_permission(self):
        from django.contrib import admin
        from apps.sync.models import PaMartRenewalAttempt
        view = admin.site._registry[PaMartRenewalAttempt]
        self.assertFalse(view.has_add_permission(None))
        self.assertFalse(view.has_change_permission(None))
        self.assertFalse(view.has_delete_permission(None))
        self.assertIsNone(view.actions)
        self.assertNotIn('listing', view.fields)
        self.assertNotIn('raw_data', view.fields)
