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
