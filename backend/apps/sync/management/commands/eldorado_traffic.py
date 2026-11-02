"""Show SDA's Eldorado traffic per store per hour (from the shared governor).

    python manage.py eldorado_traffic            # last 24 hours
    python manage.py eldorado_traffic --hours 6

Columns: read / write = requests actually sent; write_429 / read_429 =
Eldorado "Calm down, cowboy" replies; refused_* = calls SDA held back
locally (store paused or write budget used) without sending anything.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apis_sdk.clients.marketplaces.eldorado.governor import EldoradoGovernor

FIELDS = (
    'read', 'write', 'write_429', 'read_429',
    'refused_cooldown', 'refused_budget', 'refused_read_cooldown',
)


class Command(BaseCommand):
    help = "Per-store hourly Eldorado request counts and current pauses"

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24)

    def handle(self, *args, **options):
        now = time.time()
        cutoff = time.strftime('%Y-%m-%dT%H', time.gmtime(now - options['hours'] * 3600))
        snapshot = EldoradoGovernor().snapshot()
        if not snapshot:
            self.stdout.write('No Eldorado traffic recorded yet.')
            return
        for store, state in snapshot.items():
            pause = max(0, float(state.get('write_cooldown_until', 0)) - now)
            self.stdout.write(
                f"\n== {store}  writes paused: {int(pause)}s  "
                f"consecutive 429: {state.get('consecutive_429', 0)}"
            )
            self.stdout.write('hour (UTC)      ' + ' '.join(f'{f:>22}' for f in FIELDS))
            for hour, bucket in sorted((state.get('hours') or {}).items()):
                if hour < cutoff:
                    continue
                self.stdout.write(f'{hour}   ' + ' '.join(f'{int(bucket.get(f, 0)):>22}' for f in FIELDS))
