"""APScheduler daemon for cross-platform sync.

Runs the sync chain (LZT → offers → orders → reconcile) at a configurable
interval.  Designed to run as a long-lived process managed by systemd or
supervisor in production.

Usage:
    python manage.py runapscheduler              # default 5-minute interval
    python manage.py runapscheduler --interval 1 # 1-minute interval (testing)
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django_apscheduler import util as apscheduler_util
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger(__name__)

# Auto-delete old job execution logs after 7 days
MAX_EXECUTION_AGE_DAYS = 7


@apscheduler_util.close_old_connections
def run_sync_chain_job():
    """APScheduler wrapper — closes stale DB connections, then runs chain."""
    from apps.sync.orchestrator import run_sync_chain
    run_sync_chain()


@apscheduler_util.close_old_connections
def delete_old_job_executions(max_age_days=MAX_EXECUTION_AGE_DAYS):
    """Cleanup old APScheduler execution records."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age_days)


class Command(BaseCommand):
    help = 'Start the cross-platform sync scheduler (APScheduler daemon).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=None,
            help=(
                f'Sync interval in minutes '
                f'(default: {getattr(settings, "SCHEDULER_DEFAULT_INTERVAL", 5)})'
            ),
        )

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(
            timezone=getattr(settings, 'TIME_ZONE', 'UTC'),
        )
        scheduler.add_jobstore(DjangoJobStore(), 'default')

        interval = options['interval'] or getattr(settings, 'SCHEDULER_DEFAULT_INTERVAL', 5)

        # Main sync chain — runs every N minutes
        scheduler.add_job(
            run_sync_chain_job,
            trigger=IntervalTrigger(minutes=interval),
            id='sync_chain',
            name='Cross-Platform Sync Chain',
            max_instances=1,
            replace_existing=True,
        )

        # Cleanup old execution logs — runs daily
        scheduler.add_job(
            delete_old_job_executions,
            trigger=IntervalTrigger(days=1),
            id='delete_old_executions',
            name='Delete Old Job Executions',
            max_instances=1,
            replace_existing=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Sync scheduler started (interval={interval}m). Press Ctrl+C to stop.'
            )
        )

        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
            self.stdout.write(self.style.WARNING('Scheduler stopped.'))
