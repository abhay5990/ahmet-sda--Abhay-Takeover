"""Fail closed when mandatory marketplace scheduler cycles are stale.

This command is intentionally read-only.  A small systemd timer invokes it;
when it exits non-zero, the timer service restarts the scheduler process.  The
checks use durable APScheduler execution history instead of trusting a merely
``active`` systemd process, so a hung scheduler cannot silently suspend order
ingestion and pool replenishment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_apscheduler.models import DjangoJobExecution


SYNC_CHAIN_MAX_AGE_MINUTES = 15
UNBOUND_RECOVERY_MAX_AGE_MINUTES = 15


@dataclass(frozen=True)
class SchedulerHealthCheck:
    job_id: str
    max_age_minutes: int


def stale_job_ids(
    *,
    now: datetime,
    latest_run_by_job: dict[str, datetime | None],
    checks: tuple[SchedulerHealthCheck, ...],
) -> list[str]:
    """Return mandatory job IDs with no execution inside the allowed window."""
    stale: list[str] = []
    for check in checks:
        latest = latest_run_by_job.get(check.job_id)
        if latest is None or latest < now - timedelta(minutes=check.max_age_minutes):
            stale.append(check.job_id)
    return stale


class Command(BaseCommand):
    help = 'Exit non-zero when mandatory marketplace scheduler cycles are stale.'

    def _pool_sweep_max_age_minutes(self) -> int:
        from apps.sync.services.shared.feature_flags import SyncFlag, get_sync_setting

        value = get_sync_setting(SyncFlag.POOL_SWEEP, 'interval_minutes', default=30)
        try:
            interval = max(1, int(value))
        except (TypeError, ValueError):
            interval = 30
        # Two complete configured intervals plus bounded startup/DB tolerance.
        return (interval * 2) + 5

    def handle(self, *args, **options):
        checks = (
            SchedulerHealthCheck('sync_chain', SYNC_CHAIN_MAX_AGE_MINUTES),
            SchedulerHealthCheck('unbound_pool_sale_recovery', UNBOUND_RECOVERY_MAX_AGE_MINUTES),
            SchedulerHealthCheck('offer_pool_sweep', self._pool_sweep_max_age_minutes()),
            SchedulerHealthCheck('gameboost_webhook_events', 5),
        )
        now = timezone.now()
        latest_run_by_job: dict[str, datetime | None] = {}
        for check in checks:
            latest_run_by_job[check.job_id] = (
                DjangoJobExecution.objects
                .filter(job_id=check.job_id)
                .order_by('-run_time')
                .values_list('run_time', flat=True)
                .first()
            )

        stale = stale_job_ids(
            now=now,
            latest_run_by_job=latest_run_by_job,
            checks=checks,
        )
        if stale:
            raise CommandError(
                'scheduler health check failed; stale or absent jobs: ' + ', '.join(stale)
            )
        self.stdout.write(self.style.SUCCESS('scheduler health check passed'))
