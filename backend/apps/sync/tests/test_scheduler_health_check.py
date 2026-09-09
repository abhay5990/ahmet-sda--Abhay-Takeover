from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from apps.sync.management.commands.check_scheduler_health import (
    SchedulerHealthCheck,
    stale_job_ids,
)


class SchedulerHealthCheckTests(SimpleTestCase):
    def test_scheduler_health_accepts_recent_mandatory_jobs(self):
        now = timezone.now()
        checks = (
            SchedulerHealthCheck('sync_chain', 15),
            SchedulerHealthCheck('offer_pool_sweep', 9),
        )

        self.assertEqual(
            stale_job_ids(
                now=now,
                latest_run_by_job={
                    'sync_chain': now - timedelta(minutes=5),
                    'offer_pool_sweep': now - timedelta(minutes=2),
                },
                checks=checks,
            ),
            [],
        )

    def test_scheduler_health_flags_absent_and_stale_jobs(self):
        now = timezone.now()
        checks = (
            SchedulerHealthCheck('sync_chain', 15),
            SchedulerHealthCheck('offer_pool_sweep', 9),
        )

        self.assertEqual(
            stale_job_ids(
                now=now,
                latest_run_by_job={
                    'sync_chain': now - timedelta(minutes=16),
                    'offer_pool_sweep': None,
                },
                checks=checks,
            ),
            ['sync_chain', 'offer_pool_sweep'],
        )
