"""Management command: check Eldorado listing drift and reconcile.

Usage:
    python manage.py check_eldorado_drift                  # normal (threshold=5)
    python manage.py check_eldorado_drift --dry-run        # sadece sayilari goster
    python manage.py check_eldorado_drift --force          # threshold=0, herhangi drift varsa sync
    python manage.py check_eldorado_drift --store slug     # tek store
    python manage.py check_eldorado_drift --game fortnite  # tek game

Intended to run via cron 3-4 times per day.
"""

from django.core.management.base import BaseCommand

from apps.sync.services.eldorado.drift_monitor import (
    DRIFT_THRESHOLD,
    run_drift_check,
)


class Command(BaseCommand):
    help = 'Check Eldorado listing drift for variant-managed games and reconcile.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only show drift counts, do not sync.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sync on any drift (threshold=0).',
        )
        parser.add_argument(
            '--store',
            type=str,
            default='',
            help='Filter by store slug.',
        )
        parser.add_argument(
            '--game',
            type=str,
            default='',
            help='Filter by game slug (fortnite, valorant, rainbow-six-siege).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        store_filter = options['store']
        game_filter = options['game']

        threshold = 0 if force else DRIFT_THRESHOLD
        mode = "DRY-RUN" if dry_run else ("FORCE" if force else "NORMAL")

        self.stdout.write(
            f"Starting Eldorado drift check (mode={mode}, threshold={threshold})..."
        )

        summary = run_drift_check(
            dry_run=dry_run,
            threshold_override=threshold if force else None,
            store_slug=store_filter or None,
            game_slug=game_filter or None,
        )

        self.stdout.write(self.style.SUCCESS(
            f"Drift check complete: "
            f"checks={summary['checks']} "
            f"mini_syncs={summary['mini_syncs']} "
            f"errors={summary['errors']}"
        ))

        # Print details in dry-run mode
        if dry_run and summary.get('details'):
            self.stdout.write("\n--- Drift Details ---")
            for d in summary['details']:
                drift = d['drift']
                indicator = "✓" if abs(drift) <= DRIFT_THRESHOLD else "⚠"
                self.stdout.write(
                    f"  {indicator} {d['store']}/{d['game']}/{d['variant']}: "
                    f"remote={d['remote']} local={d['local']} drift={drift:+d}"
                )
