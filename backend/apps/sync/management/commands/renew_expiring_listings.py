"""Auto-renew SDA listings on every marketplace whose offers expire.

Coverage (checked live 5 Nov 2026):
* PlayerAuctions — offers expire after 30 days. Mart renews through the
  existing exact-ID ``renew_expiring_playerauctions`` lane (MCT official
  renewal). PA Shop has no API, so it cannot be renewed automatically.
* Eldorado — offers expire ~21 days after their last save. Renewed here by an
  unchanged full re-save, counted only when a fresh read shows a later expiry
  (``apps.sync.services.eldorado.renewal``).
* GameBoost — offers carry no expiry (``status/listed_at`` only); nothing to renew.
* G2G / U7Buy — SDA has no live listings there today; nothing to renew.

Dry-run by default. ``--execute`` needs the ``sync.renew_expiring_listings``
switch. Eldorado stops the whole run on the first save that does not move the
expiry, a held/busy/cowboy write, or a failed verification.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.sync.services.shared.feature_flags import RENEWABLE_PROVIDERS, unified_renewal_providers

DEFAULT_LEAD_HOURS = 96
DEFAULT_ELDORADO_READS = 40
MAX_ELDORADO_READS = 200
DEFAULT_ELDORADO_RENEWALS = 10
MAX_ELDORADO_RENEWALS = 50
NO_EXPIRY_PROVIDERS = {
    'gameboost': 'GameBoost offers do not expire',
    'g2g': 'no SDA listings on G2G',
    'u7buy': 'no SDA listings on U7Buy',
}


class Command(BaseCommand):
    help = 'Auto-renew offers before they expire on every marketplace that expires them (dry-run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--lead-hours', type=int, default=DEFAULT_LEAD_HOURS,
                            help='Renew offers expiring within this many hours (default 96).')
        parser.add_argument('--providers', default='',
                            help='Comma list to limit this run (default: the providers the switch covers).')
        parser.add_argument('--eldorado-reads', type=int, default=DEFAULT_ELDORADO_READS,
                            help=f'Max Eldorado offers read per run (default {DEFAULT_ELDORADO_READS}).')
        parser.add_argument('--eldorado-renewals', type=int, default=DEFAULT_ELDORADO_RENEWALS,
                            help=f'Max Eldorado re-saves per run (default {DEFAULT_ELDORADO_RENEWALS}).')
        parser.add_argument('--pa-limit', type=int, default=25)

    def handle(self, *args, **options):
        execute = options['execute']
        lead_hours = max(1, int(options['lead_hours']))
        reads = int(options['eldorado_reads'])
        renewals = int(options['eldorado_renewals'])
        if not 1 <= reads <= MAX_ELDORADO_READS:
            raise CommandError(f'--eldorado-reads must be between 1 and {MAX_ELDORADO_READS}')
        if not 1 <= renewals <= MAX_ELDORADO_RENEWALS:
            raise CommandError(f'--eldorado-renewals must be between 1 and {MAX_ELDORADO_RENEWALS}')

        enabled = unified_renewal_providers()
        if execute and not enabled:
            raise CommandError('Auto-renewal is held; turn on sync.renew_expiring_listings first.')
        requested = [p.strip().lower() for p in str(options['providers']).split(',') if p.strip()]
        providers = requested or list(enabled or RENEWABLE_PROVIDERS)
        unknown = [p for p in providers if p not in RENEWABLE_PROVIDERS and p not in NO_EXPIRY_PROVIDERS]
        if unknown:
            raise CommandError(f'Unknown provider(s): {", ".join(unknown)}')
        if execute:
            blocked = [p for p in providers if p in RENEWABLE_PROVIDERS and p not in enabled]
            if blocked:
                raise CommandError(f'Auto-renewal switch does not cover: {", ".join(blocked)}')

        for provider, why in NO_EXPIRY_PROVIDERS.items():
            if provider in providers or not requested:
                self.stdout.write(f'{provider}: nothing to renew ({why})')

        if 'playerauctions' in providers:
            self.stdout.write('playerauctions:')
            args = ['--lead-hours', str(lead_hours), '--limit', str(max(1, min(100, int(options['pa_limit']))))]
            if execute:
                args.insert(0, '--execute')
            call_command('renew_expiring_playerauctions', *args, stdout=self.stdout, stderr=self.stderr)

        if 'eldorado' in providers:
            self._eldorado(execute=execute, lead_hours=lead_hours, reads=reads, renewals=renewals)

    def _eldorado(self, *, execute: bool, lead_hours: int, reads: int, renewals: int) -> None:
        from apps.sync.services.eldorado.renewal import eldorado_candidates, renew_eldorado_listing

        now = timezone.now()
        cutoff = now + timedelta(hours=lead_hours)
        candidates = eldorado_candidates(now=now, cutoff=cutoff, limit=reads)
        stats: dict[str, int] = {}
        saves = 0
        stopped = ''
        for listing in candidates:
            if saves >= renewals:
                stats['left_for_next_run'] = stats.get('left_for_next_run', 0) + 1
                continue
            try:
                decision = renew_eldorado_listing(listing, now=now, cutoff=cutoff, execute=execute)
            except Exception as exc:  # one bad row must not stop the others
                stats['failed'] = stats.get('failed', 0) + 1
                self.stdout.write(self.style.ERROR(f'FAILED {listing.store_listing_id}: {type(exc).__name__}'))
                continue
            stats[decision.outcome] = stats.get(decision.outcome, 0) + 1
            if decision.outcome in ('renewed', 'unproven', 'failed') and decision.reason.startswith(('verified', 'saved', 'verify', 'save')):
                saves += 1
            if decision.outcome == 'renewed':
                self.stdout.write(self.style.SUCCESS(
                    f'RENEWED {listing.store_listing_id}: {decision.previous:%Y-%m-%d} → {decision.verified:%Y-%m-%d}'))
            elif decision.reason == 'dry_run_would_renew':
                self.stdout.write(f'READY {listing.store_listing_id}: expires {decision.previous}')
            elif decision.outcome in ('unproven', 'failed', 'held_sale'):
                self.stdout.write(self.style.WARNING(f'{decision.outcome.upper()} {listing.store_listing_id}: {decision.reason}'))
            if decision.stop_run:
                stopped = f'{decision.outcome}:{decision.reason}'
                break
        summary = ' '.join(f'{k}={v}' for k, v in sorted(stats.items())) or 'nothing due'
        self.stdout.write(f'eldorado: {"EXECUTE" if execute else "DRY RUN"} candidates={len(candidates)} {summary}'
                          + (f' STOPPED ({stopped})' if stopped else ''))
