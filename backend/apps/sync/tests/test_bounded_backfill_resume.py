from django.test import TestCase

from apps.integrations.models import IntegrationAccount
from apps.sync.enums import CheckpointStatus, ResourceType, SyncMode
from apps.sync.models import SyncCheckpoint
from apps.sync.services.base import BaseSyncService


class _BoundedBackfillService(BaseSyncService):
    resource_type = ResourceType.ORDERS

    def __init__(self, max_pages):
        self.max_pages = max_pages
        self.fetched_pages = []

    def fetch_page(self, account, checkpoint):
        page = int(checkpoint.cursor or '1')
        self.fetched_pages.append(page)
        return [{'id': f'order-{page}'}], str(page + 1) if page < 5 else ''

    def extract_remote_id(self, item):
        return item['id']

    def parse_and_apply(self, raw_payload):
        return 'created'


class BoundedBackfillResumeTests(TestCase):
    def setUp(self):
        self.account = IntegrationAccount.objects.create(
            name='Bounded PA backfill test',
            slug='bounded-pa-backfill-test',
            provider='playerauctions',
            role='sell',
        )

    def test_page_limit_preserves_next_page_for_nonduplicating_resume(self):
        first = _BoundedBackfillService(max_pages=2)
        first_run = first.run(self.account, SyncMode.BACKFILL)

        checkpoint = SyncCheckpoint.objects.get(
            integration_account=self.account,
            resource_type=ResourceType.ORDERS,
            mode=SyncMode.BACKFILL,
        )
        self.assertEqual(first.fetched_pages, [1, 2])
        self.assertEqual(first_run.processed_count, 2)
        self.assertEqual(first_run.meta['page_limit_reached'], 2)
        self.assertEqual(checkpoint.status, CheckpointStatus.ACTIVE)
        self.assertEqual(checkpoint.cursor, '3')

        second = _BoundedBackfillService(max_pages=2)
        second_run = second.run(self.account, SyncMode.BACKFILL)
        checkpoint.refresh_from_db()
        self.assertEqual(second.fetched_pages, [3, 4])
        self.assertEqual(second_run.processed_count, 2)
        self.assertEqual(second_run.meta['page_limit_reached'], 2)
        self.assertEqual(checkpoint.status, CheckpointStatus.ACTIVE)
        self.assertEqual(checkpoint.cursor, '5')
