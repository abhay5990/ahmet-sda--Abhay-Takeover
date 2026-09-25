from unittest.mock import patch

from django.test import SimpleTestCase

from apps.sync.management.commands import runapscheduler


class _FakeScheduler:
    def __init__(self, *_args, **_kwargs):
        self.jobs = []

    def add_jobstore(self, *_args, **_kwargs):
        return None

    def add_job(self, _func, **kwargs):
        self.jobs.append(kwargs)

    def start(self):
        return None


class SchedulerBootRecoveryTests(SimpleTestCase):
    @patch.object(runapscheduler.Command, '_check_telegram')
    @patch('apps.sync.management.commands.runapscheduler.BlockingScheduler')
    @patch('apps.sync.services.shared.feature_flags.get_sync_setting')
    def test_required_recovery_jobs_start_immediately(
        self,
        get_sync_setting,
        blocking_scheduler,
        _check_telegram,
    ):
        # Use a harmless scheduler stub so registration can be inspected without
        # starting a worker or touching the job-store database.
        fake_scheduler = _FakeScheduler()
        blocking_scheduler.return_value = fake_scheduler
        get_sync_setting.return_value = 30

        runapscheduler.Command().handle(interval=5)

        jobs = {job['id']: job for job in fake_scheduler.jobs}
        self.assertIn('next_run_time', jobs['playerauctions_email_recovery'])
        self.assertIn('next_run_time', jobs['unbound_pool_sale_recovery'])
        self.assertEqual(
            jobs['playerauctions_email_recovery']['max_instances'], 1,
        )
        self.assertEqual(
            jobs['unbound_pool_sale_recovery']['max_instances'], 1,
        )
