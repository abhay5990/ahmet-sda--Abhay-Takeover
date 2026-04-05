"""Bulk import LZT items into RawPayload (+ optional parse).

Supports two data sources:
  - file: Read from a local JSON file (fast, for large backfills)
  - api:  Fetch all pages from LZT API (no file needed, slower)

Usage:
    # From JSON file (default)
    python manage.py import_lzt_orders <account-slug> --source file <json-path>
    python manage.py import_lzt_orders <account-slug> <json-path>

    # From LZT API
    python manage.py import_lzt_orders <account-slug> --source api
    python manage.py import_lzt_orders <account-slug> --source api --phase ingest

    # Common options
    python manage.py import_lzt_orders <account-slug> <json-path> --batch-size 1000
    python manage.py import_lzt_orders <account-slug> --source api --dry-run
"""
import time

import ijson
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.sync.enums import ParseStatus, SyncMode, SyncPhase, SyncRunStatus
from apps.sync.models import SyncRun
from apps.sync.services.lzt.service import LztOwnedProductSyncService


class Command(BaseCommand):
    help = 'Bulk import LZT items from JSON file or API into RawPayload and OwnedProduct.'

    def add_arguments(self, parser):
        parser.add_argument(
            'account',
            type=str,
            help='IntegrationAccount slug (e.g. "lzt-main")',
        )
        parser.add_argument(
            'json_path',
            nargs='?',
            default=None,
            type=str,
            help='Path to the LZT JSON file (required for --source file)',
        )
        parser.add_argument(
            '--source',
            type=str,
            choices=['file', 'api'],
            default='file',
            help='Data source: "file" (JSON) or "api" (fetch from LZT API)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Items per batch (default: 500)',
        )
        parser.add_argument(
            '--phase',
            type=str,
            choices=[SyncPhase.FULL, SyncPhase.INGEST],
            default=SyncPhase.FULL,
            help='full = ingest + parse, ingest = raw only (parse later)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate setup and count items without importing',
        )

    def handle(self, *args, **options):
        slug = options['account']
        source = options['source']
        json_path = options['json_path']
        batch_size = options['batch_size']
        phase = options['phase']
        dry_run = options['dry_run']

        # 1. Validate arguments
        if source == 'file' and not json_path:
            raise CommandError(
                'json_path is required when --source file. '
                'Usage: import_lzt_orders <account> <json-path>'
            )

        # 2. Account lookup
        try:
            account = IntegrationAccount.objects.select_related(
                'credential',
            ).get(slug=slug, is_active=True)
        except IntegrationAccount.DoesNotExist:
            raise CommandError(
                f'Active IntegrationAccount with slug "{slug}" not found.'
            )

        # 3. Dispatch to source-specific handler
        if source == 'api':
            self._handle_api(account, batch_size, phase, dry_run)
        else:
            self._handle_file(account, json_path, batch_size, phase, dry_run)

    # ── File source ────────────────────────────────────────────────────

    def _handle_file(self, account, json_path, batch_size, phase, dry_run):
        """Import from a local JSON file (existing behavior)."""
        try:
            f = open(json_path, 'rb')
        except FileNotFoundError:
            raise CommandError(f'JSON file not found: {json_path}')

        if dry_run:
            count = 0
            for _ in ijson.items(f, 'item', use_float=True):
                count += 1
            f.close()
            self.stdout.write(self.style.SUCCESS(
                f'Dry run: {count:,} items found in {json_path}'
            ))
            return

        service = LztOwnedProductSyncService()
        ingest_only = phase == SyncPhase.INGEST

        run = SyncRun.objects.create(
            integration_account=account,
            resource_type=service.resource_type,
            mode=SyncMode.BACKFILL,
        )
        self.stdout.write(
            f'SyncRun {run.pk} started: source=file account={account.slug} phase={phase}'
        )

        start = time.time()
        stats = _Stats()
        batch_buffer = []

        try:
            for item in ijson.items(f, 'item', use_float=True):
                stats.total += 1
                batch_buffer.append(item)

                if len(batch_buffer) >= batch_size:
                    stats.batch_num += 1
                    _flush_batch(service, account, batch_buffer, ingest_only, run, stats)
                    batch_buffer = []
                    self._report_progress(run, stats, start)

            # Flush remaining
            if batch_buffer:
                stats.batch_num += 1
                _flush_batch(service, account, batch_buffer, ingest_only, run, stats)

            run.processed_count = stats.total
            run.finish(SyncRunStatus.COMPLETED)

        except Exception as exc:
            run.processed_count = stats.total
            run.finish(SyncRunStatus.FAILED)
            f.close()
            raise CommandError(f'Import failed at item {stats.total}: {exc}')

        f.close()
        self._report_final(run, stats, start, ingest_only)

    # ── API source ─────────────────────────────────────────────────────

    def _handle_api(self, account, batch_size, phase, dry_run):
        """Import by fetching all pages from LZT API."""
        # Build client from account credentials
        if not hasattr(account, 'credential') or not account.credential:
            raise CommandError(
                f'Account "{account.slug}" has no credential configured.'
            )

        provider = get_provider('lzt')
        client = get_or_build_client('lzt', account.credential)

        if dry_run:
            self.stdout.write('Dry run: fetching page 1 to estimate total...')
            result = provider.fetch_orders(client, params={'page': 1})
            if not result.ok:
                error_msg = result.error.message if result.error else 'Unknown error'
                raise CommandError(f'LZT API error: {error_msg}')
            page_data = result.data
            self.stdout.write(self.style.SUCCESS(
                f'Dry run: ~{page_data.total_items:,} total items, '
                f'{page_data.per_page} per page, '
                f'~{(page_data.total_items // page_data.per_page) + 1} pages'
            ))
            return

        service = LztOwnedProductSyncService(provider, client)
        ingest_only = phase == SyncPhase.INGEST

        run = SyncRun.objects.create(
            integration_account=account,
            resource_type=service.resource_type,
            mode=SyncMode.BACKFILL,
        )
        self.stdout.write(
            f'SyncRun {run.pk} started: source=api account={account.slug} phase={phase}'
        )

        start = time.time()
        stats = _Stats()
        batch_buffer = []
        current_page = 1

        try:
            while True:
                # Fetch one page from API
                result = provider.fetch_orders(
                    client, params={'page': current_page},
                )

                if not result.ok:
                    error_msg = result.error.message if result.error else 'Unknown error'
                    raise RuntimeError(
                        f'LZT API error on page {current_page}: {error_msg}'
                    )

                page_data = result.data
                items = page_data.items if page_data else []

                if not items:
                    self.stdout.write(
                        f'  page {current_page}: empty — done fetching'
                    )
                    break

                self.stdout.write(
                    f'  page {current_page}: fetched {len(items)} items '
                    f'(total so far: {stats.total + len(items):,})'
                )

                for item in items:
                    stats.total += 1
                    batch_buffer.append(item)

                    if len(batch_buffer) >= batch_size:
                        stats.batch_num += 1
                        _flush_batch(
                            service, account, batch_buffer,
                            ingest_only, run, stats,
                        )
                        batch_buffer = []
                        self._report_progress(run, stats, start)

                if not page_data.has_next_page:
                    self.stdout.write(
                        f'  page {current_page}: last page reached'
                    )
                    break

                current_page += 1

            # Flush remaining
            if batch_buffer:
                stats.batch_num += 1
                _flush_batch(
                    service, account, batch_buffer,
                    ingest_only, run, stats,
                )

            run.processed_count = stats.total
            run.finish(SyncRunStatus.COMPLETED)

        except Exception as exc:
            run.processed_count = stats.total
            run.finish(SyncRunStatus.FAILED)
            raise CommandError(
                f'API import failed at page {current_page}, '
                f'item {stats.total}: {exc}'
            )

        self._report_final(run, stats, start, ingest_only)

    # ── Shared helpers ─────────────────────────────────────────────────

    def _report_progress(self, run, stats, start):
        """Update SyncRun and print batch progress."""
        run.processed_count = stats.total
        run.save(update_fields=[
            'processed_count', 'created_count',
            'updated_count', 'error_count', 'updated_at',
        ])
        elapsed = time.time() - start
        rate = stats.total / elapsed if elapsed > 0 else 0
        self.stdout.write(
            f'  batch {stats.batch_num}: {stats.total:,} items '
            f'({rate:.0f} items/s)'
        )

    def _report_final(self, run, stats, start, ingest_only):
        """Print final import summary."""
        elapsed = time.time() - start
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Import complete!'))
        self.stdout.write(f'  Total items:      {stats.total:,}')
        self.stdout.write(f'  Ingested (raw):   {stats.ingested:,}')
        self.stdout.write(f'  No loginData:     {stats.skipped_no_login:,}')
        if not ingest_only:
            self.stdout.write(f'  Parsed OK:        {stats.parse_ok:,}')
            self.stdout.write(f'  Parse failed:     {stats.parse_fail:,}')
            self.stdout.write(f'  Created:          {run.created_count:,}')
            self.stdout.write(f'  Updated:          {run.updated_count:,}')
            self.stdout.write(f'  Errors:           {run.error_count:,}')
        self.stdout.write(f'  Time:             {elapsed:.1f}s')
        self.stdout.write(f'  SyncRun:          {run.pk}')


class _Stats:
    """Mutable counters shared between flush_batch and the command."""
    __slots__ = (
        'total', 'ingested', 'skipped_no_login',
        'parse_ok', 'parse_fail', 'batch_num',
    )

    def __init__(self):
        self.total = 0
        self.ingested = 0
        self.skipped_no_login = 0
        self.parse_ok = 0
        self.parse_fail = 0
        self.batch_num = 0


def _flush_batch(service, account, buffer, ingest_only, run, stats):
    """Process a batch of items — shared by both file and API sources."""
    with transaction.atomic():
        for item in buffer:
            remote_id = service.extract_remote_id(item)
            if not remote_id:
                continue

            raw = service._ingest_raw(account, remote_id, item)
            stats.ingested += 1

            if not item.get('loginData'):
                if raw.parse_status == ParseStatus.PENDING:
                    raw.meta = {**raw.meta, 'no_login_data': True}
                    raw.save(update_fields=['meta', 'updated_at'])
                stats.skipped_no_login += 1
            elif not ingest_only:
                service._try_parse(raw, run)
                if raw.parse_status == ParseStatus.PARSED:
                    stats.parse_ok += 1
                elif raw.parse_status == ParseStatus.FAILED:
                    stats.parse_fail += 1
