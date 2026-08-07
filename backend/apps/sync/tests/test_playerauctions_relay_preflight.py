from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.sync.enums import SyncMode, SyncPhase
from apps.sync.services.base import BaseSyncService
from apps.sync.services.playerauctions.orders.service import (
    PlayerAuctionsOrderSyncService,
)


class PlayerAuctionsRelayPreflightTests(SimpleTestCase):
    def test_remote_sync_requires_relay_session_before_fetching(self):
        client = Mock()
        client.refresh_relay_session.return_value = True
        account = Mock(slug='playerauctions-csgosmurfkings')
        service = PlayerAuctionsOrderSyncService(client=client)

        with patch.object(BaseSyncService, 'run', return_value='sync-run') as base_run:
            result = service.run(account, SyncMode.INCREMENTAL)

        self.assertEqual(result, 'sync-run')
        client.reset_auth_failure.assert_called_once_with()
        client.refresh_relay_session.assert_called_once_with()
        base_run.assert_called_once_with(account, SyncMode.INCREMENTAL, 'full')

    def test_process_only_run_does_not_call_the_relay(self):
        client = Mock()
        account = Mock(slug='playerauctions-csgosmurfkings')
        service = PlayerAuctionsOrderSyncService(client=client)

        with patch.object(BaseSyncService, 'run', return_value='sync-run'):
            service.run(account, SyncMode.INCREMENTAL, SyncPhase.PROCESS)

        client.refresh_relay_session.assert_not_called()

    def test_relay_preflight_failure_blocks_remote_fetch(self):
        client = Mock()
        client.refresh_relay_session.return_value = False
        service = PlayerAuctionsOrderSyncService(client=client)

        with self.assertRaisesRegex(RuntimeError, 'relay session preflight failed'):
            service.run(Mock(), SyncMode.INCREMENTAL)
