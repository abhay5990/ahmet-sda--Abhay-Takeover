"""APScheduler daemon for cross-platform sync.

Runs the sync chain (LZT → offers → orders → reconcile) at a configurable
interval.  Designed to run as a long-lived process managed by systemd or
supervisor in production.

Usage:
    python manage.py runapscheduler              # default 5-minute interval
    python manage.py runapscheduler --interval 1 # 1-minute interval (testing)
"""

import logging
from datetime import datetime

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

# Module-level scheduler reference for dynamic rescheduling
_scheduler: BlockingScheduler | None = None


@apscheduler_util.close_old_connections
def run_sync_chain_job():
    """APScheduler wrapper — closes stale DB connections, then runs chain."""
    from apps.sync.orchestrator import run_sync_chain
    run_sync_chain()


_review_monitor_first_run = True

@apscheduler_util.close_old_connections
def run_review_monitor_job():
    """APScheduler wrapper — checks all Eldorado accounts for new negative reviews."""
    from apps.sync.services.shared.feature_flags import SyncFlag, is_sync_feature_enabled
    if not is_sync_feature_enabled(SyncFlag.REVIEW_MONITOR):
        return
    global _review_monitor_first_run
    from apps.sync.services.eldorado.reviews.monitor import EldoradoReviewMonitor
    EldoradoReviewMonitor().check_all_accounts(first_run=_review_monitor_first_run)
    _review_monitor_first_run = False


@apscheduler_util.close_old_connections
def run_order_status_refresh_job():
    """APScheduler wrapper — refreshes non-final order statuses (Eldorado/Gameboost)."""
    from apps.sync.services.shared.feature_flags import SyncFlag, is_sync_feature_enabled
    if not is_sync_feature_enabled(SyncFlag.ORDER_STATUS_REFRESH):
        return
    from apps.sync.services.order_status_refresh import run_order_status_refresh
    run_order_status_refresh()


POOL_SWEEP_DEFAULT_INTERVAL = 30  # minutes


@apscheduler_util.close_old_connections
def run_pool_sweep_job():
    """APScheduler wrapper — checks all active offer pools and replenishes if needed.

    Reads interval_minutes from SyncFeatureFlag.value on every run and
    reschedules itself if the configured interval has changed.
    """
    from apps.sync.services.shared.feature_flags import SyncFlag, is_sync_feature_enabled, get_sync_setting
    if not is_sync_feature_enabled(SyncFlag.POOL_SWEEP):
        return

    from apps.posting.services.pool.checker import sweep_all_pools
    sweep_all_pools()

    # Dynamic interval: reschedule if DB value differs from current trigger
    _maybe_reschedule_pool_sweep()


def _maybe_reschedule_pool_sweep() -> None:
    """Reschedule pool sweep job if DB interval differs from current trigger."""
    global _scheduler
    if _scheduler is None:
        return

    from apps.sync.services.shared.feature_flags import SyncFlag, get_sync_setting
    db_interval = get_sync_setting(SyncFlag.POOL_SWEEP, 'interval_minutes', default=POOL_SWEEP_DEFAULT_INTERVAL)
    try:
        db_interval = max(1, int(db_interval))
    except (TypeError, ValueError):
        return

    job = _scheduler.get_job('offer_pool_sweep')
    if job is None:
        return

    current_interval = getattr(job.trigger, 'interval', None)
    if current_interval is None:
        return

    current_minutes = int(current_interval.total_seconds() / 60)
    if current_minutes != db_interval:
        _scheduler.reschedule_job(
            'offer_pool_sweep',
            trigger=IntervalTrigger(minutes=db_interval),
        )
        logger.info('pool_sweep: rescheduled interval %d → %d minutes', current_minutes, db_interval)


@apscheduler_util.close_old_connections
def run_pause_expiring_listings_job():
    """APScheduler wrapper — pauses listings approaching marketplace expiry."""
    from apps.sync.services.shared.feature_flags import SyncFlag, is_sync_feature_enabled
    if not is_sync_feature_enabled(SyncFlag.PAUSE_EXPIRING):
        return
    from django.core.management import call_command
    call_command('pause_expiring_listings', '--execute')


@apscheduler_util.close_old_connections
def run_robuxcrate_batch_processor_job():
    """APScheduler wrapper — processes pending RobuxCrate order batches."""
    from apps.tools.services.robuxcrate import process_pending_batches
    process_pending_batches()

@apscheduler_util.close_old_connections
def run_robux_auto_fulfillment_job():
    """APScheduler wrapper — automated Robux delivery via Telegram bot."""
    from apps.tools.services.robux_auto_fulfillment import run_robux_auto_fulfillment_job as _job
    _job()


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
        global _scheduler

        scheduler = BlockingScheduler(
            timezone=getattr(settings, 'TIME_ZONE', 'UTC'),
        )
        _scheduler = scheduler
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

        # NOTE: Dropship poster + cleaner moved to run_dropship_scheduler command.

        # Negative review monitor — runs every 10 minutes
        scheduler.add_job(
            run_review_monitor_job,
            trigger=IntervalTrigger(minutes=10),
            id='eldorado_review_monitor',
            name='Eldorado Negative Review Monitor',
            max_instances=1,
            replace_existing=True,
        )

        # Order status refresh — runs every 60 minutes, starts immediately
        scheduler.add_job(
            run_order_status_refresh_job,
            trigger=IntervalTrigger(minutes=60),
            id='order_status_refresh',
            name='Order Status Refresh (Eldorado/Gameboost)',
            max_instances=1,
            replace_existing=True,
            next_run_time=datetime.now(),
        )

        # Offer pool sweep — interval configurable via admin (SyncFeatureFlag value)
        from apps.sync.services.shared.feature_flags import SyncFlag, get_sync_setting
        pool_sweep_interval = get_sync_setting(
            SyncFlag.POOL_SWEEP, 'interval_minutes', default=POOL_SWEEP_DEFAULT_INTERVAL,
        )
        try:
            pool_sweep_interval = max(1, int(pool_sweep_interval))
        except (TypeError, ValueError):
            pool_sweep_interval = POOL_SWEEP_DEFAULT_INTERVAL

        scheduler.add_job(
            run_pool_sweep_job,
            trigger=IntervalTrigger(minutes=pool_sweep_interval),
            id='offer_pool_sweep',
            name='Offer Pool Auto-Restock Sweep',
            max_instances=1,
            replace_existing=True,
        )

        # Pause expiring listings — runs every 3 hours
        scheduler.add_job(
            run_pause_expiring_listings_job,
            trigger=IntervalTrigger(hours=3),
            id='pause_expiring_listings',
            name='Pause Expiring Listings (Eldorado/PA)',
            max_instances=1,
            replace_existing=True,
        )

        # RobuxCrate batch processor — runs every 5 minutes
        scheduler.add_job(
            run_robuxcrate_batch_processor_job,
            trigger=IntervalTrigger(minutes=5),
            id='robuxcrate_batch_processor',
            name='RobuxCrate Batch Order Processor',
            max_instances=1,
            replace_existing=True,
        )
        # Robux auto-fulfillment — detect orders, poll Telegram, create batches
        scheduler.add_job(
            run_robux_auto_fulfillment_job,
            trigger=IntervalTrigger(minutes=5),
            id='robux_auto_fulfillment',
            name='Robux Auto-Fulfillment (Telegram Bot)',
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

        self._check_telegram()

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

    def _check_telegram(self) -> None:
        """Verify Telegram bot connectivity on startup and print the result."""
        try:
            from apps.integrations.models import ServiceCredential
            from apps.integrations.services.registry import get_service

            credential = (
                ServiceCredential.objects
                .filter(service_type='telegram', is_active=True)
                .first()
            )
            if not credential:
                self.stdout.write(self.style.WARNING(
                    'Telegram: no active notification credential — review alerts disabled'
                ))
                return

            service = get_service('telegram')
            client = service.build_client(credential)
            ok, msg = service.test_connection(client)
            if ok:
                self.stdout.write(self.style.SUCCESS(f'Telegram: {msg}'))
            else:
                self.stdout.write(self.style.WARNING(f'Telegram: {msg}'))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Telegram check error: {exc}'))
