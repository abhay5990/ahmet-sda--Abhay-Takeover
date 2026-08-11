from django.test import TestCase

from apps.integrations.models import IntegrationAccount
from apps.sync.enums import ParseStatus, ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService


class _FailingOnceOrderSync(BaseSyncService):
    resource_type = ResourceType.ORDERS

    def __init__(self, fail_parse: bool):
        self.fail_parse = fail_parse
        self.fetch_calls = 0

    def fetch_page(self, account, checkpoint):
        self.fetch_calls += 1
        if self.fetch_calls == 1:
            return [{'id': 'pa-order-16364033'}], 'next-page'
        return [{'id': 'older-pa-order'}], ''

    def extract_remote_id(self, item):
        return item['id']

    def parse_and_apply(self, raw_payload):
        if self.fail_parse:
            raise RuntimeError('transient local apply failure')
        return 'created'


class _PermanentlyFailingOrderSync(BaseSyncService):
    """Single-page order sync whose parse ALWAYS fails (poison pill)."""

    resource_type = ResourceType.ORDERS
    MAX_PARSE_RETRY_ATTEMPTS = 2

    def __init__(self):
        self.fetch_calls = 0

    def fetch_page(self, account, checkpoint):
        self.fetch_calls += 1
        return [{'id': 'poison-order'}], ''

    def extract_remote_id(self, item):
        return item['id']

    def parse_and_apply(self, raw_payload):
        raise RuntimeError('permanent bad data')


class RetrySafeIncrementalSyncTests(TestCase):
    def setUp(self):
        self.account = IntegrationAccount.objects.create(
            name='Retry-safe PA test',
            slug='retry-safe-pa-test',
            provider='playerauctions',
            role='sell',
        )

    def test_failed_payload_does_not_advance_checkpoint_and_retries(self):
        failed_sync = _FailingOnceOrderSync(fail_parse=True)
        failed_sync.run(
            self.account,
            SyncMode.INCREMENTAL,
        )

        checkpoint = SyncCheckpoint.objects.get(
            integration_account=self.account,
            resource_type=ResourceType.ORDERS,
            mode=SyncMode.INCREMENTAL,
        )
        raw = RawPayload.objects.get(
            integration_account=self.account,
            resource_type=ResourceType.ORDERS,
            remote_id='pa-order-16364033',
        )
        self.assertEqual(raw.parse_status, ParseStatus.FAILED)
        self.assertEqual(checkpoint.last_seen_remote_id, '')
        self.assertEqual(failed_sync.fetch_calls, 1)

        retry_sync = _FailingOnceOrderSync(fail_parse=False)
        retry_sync.run(
            self.account,
            SyncMode.INCREMENTAL,
        )

        checkpoint.refresh_from_db()
        raw.refresh_from_db()
        self.assertEqual(raw.parse_status, ParseStatus.PARSED)
        self.assertEqual(checkpoint.last_seen_remote_id, 'pa-order-16364033')
        self.assertEqual(retry_sync.fetch_calls, 2)

    def test_permanent_failure_is_quarantined_and_stops_blocking(self):
        """A deterministically un-parseable order must not stall fetch forever.

        While it has retry budget it blocks the checkpoint (transient-recovery
        window). After MAX_PARSE_RETRY_ATTEMPTS it is quarantined: kept FAILED
        for manual review, but the checkpoint advances past it so newer orders
        and older pages keep flowing.
        """
        # Run 1: first failure — still within budget, so it blocks.
        run1 = _PermanentlyFailingOrderSync().run(
            self.account, SyncMode.INCREMENTAL,
        )
        checkpoint = SyncCheckpoint.objects.get(
            integration_account=self.account,
            resource_type=ResourceType.ORDERS,
            mode=SyncMode.INCREMENTAL,
        )
        raw = RawPayload.objects.get(
            integration_account=self.account,
            resource_type=ResourceType.ORDERS,
            remote_id='poison-order',
        )
        self.assertEqual(raw.parse_status, ParseStatus.FAILED)
        self.assertEqual(raw.meta.get('parse_attempts'), 1)
        self.assertEqual(checkpoint.last_seen_remote_id, '')
        self.assertTrue(
            run1.meta.get('checkpoint_blocked_on_parse_failure'),
        )

        # Run 2: budget exhausted (attempts reaches 2) — quarantine + advance.
        run2 = _PermanentlyFailingOrderSync().run(
            self.account, SyncMode.INCREMENTAL,
        )
        checkpoint.refresh_from_db()
        raw.refresh_from_db()
        self.assertEqual(raw.parse_status, ParseStatus.FAILED)
        self.assertEqual(raw.meta.get('parse_attempts'), 2)
        # Checkpoint has now advanced past the poison order — fetch is unblocked.
        self.assertEqual(checkpoint.last_seen_remote_id, 'poison-order')
        self.assertIn('poison-order', run2.meta.get('quarantined_remote_ids', []))
