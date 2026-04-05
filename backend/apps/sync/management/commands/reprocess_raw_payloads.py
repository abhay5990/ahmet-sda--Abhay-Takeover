import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.models import IntegrationAccount
from apps.sync.enums import ParseStatus, ResourceType, SyncRunStatus
from apps.sync.models import RawPayload, SyncRun
from apps.sync.services.registry import build_service, get_service_class


class Command(BaseCommand):
    help = (
        'Reprocess raw payloads without hitting remote APIs. '
        'Useful for retrying failed parses or re-applying after '
        'mapper/model changes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'account',
            type=str,
            help='IntegrationAccount slug',
        )
        parser.add_argument(
            '--status',
            type=str,
            nargs='+',
            choices=[
                ParseStatus.FAILED,
                ParseStatus.PENDING,
                ParseStatus.PARSED,
            ],
            default=[ParseStatus.FAILED],
            help=(
                'Which parse statuses to reprocess. '
                'Default: failed only. Use --status parsed to re-apply '
                'all previously parsed payloads (e.g. after model changes).'
            ),
        )
        parser.add_argument(
            '--resource',
            type=str,
            choices=[r.value for r in ResourceType],
            default=ResourceType.ORDERS,
            help='Resource type to reprocess (default: orders)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Maximum number of rows to process (0 = unlimited)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show how many rows would be reprocessed without doing it',
        )
        parser.add_argument(
            '--bulk',
            action='store_true',
            help=(
                'Bulk mode: warm in-memory caches (game, owned_product), '
                'process in transaction batches. '
                'Much faster for large reprocesses.'
            ),
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Rows per transaction batch in bulk mode (default: 500)',
        )

    def handle(self, *args, **options):
        slug = options['account']
        statuses = options['status']
        resource = options['resource']
        limit = options['limit']
        dry_run = options['dry_run']
        bulk = options['bulk']
        batch_size = options['batch_size']

        # 1. Account lookup
        try:
            account = IntegrationAccount.objects.select_related(
                'credential',
            ).get(slug=slug, is_active=True)
        except IntegrationAccount.DoesNotExist:
            raise CommandError(
                f'Active IntegrationAccount with slug "{slug}" not found.'
            )

        # 2. Build queryset
        qs = RawPayload.objects.filter(
            integration_account=account,
            resource_type=resource,
            parse_status__in=statuses,
        ).order_by('fetched_at')

        total = qs.count()

        if dry_run:
            self.stdout.write(
                f"Would reprocess {total} rows "
                f"(statuses={statuses}, resource={resource})."
            )
            return

        if total == 0:
            self.stdout.write("No matching rows to reprocess.")
            return

        effective_count = min(total, limit) if limit else total

        # 3. Resolve service (no client needed — reprocess is parse-only)
        if get_service_class(resource, account.provider) is None:
            raise CommandError(
                f'No sync service registered for '
                f'({resource}, "{account.provider}").'
            )

        service = build_service(resource, account.provider)

        # 4. Bulk mode: warm caches
        if bulk:
            self._warm_caches(resource)

        # 5. Reset statuses → pending
        if limit:
            target_pks = list(qs.values_list('pk', flat=True)[:limit])
            reset_qs = RawPayload.objects.filter(pk__in=target_pks)
        else:
            reset_qs = qs

        reset_count = reset_qs.filter(
            parse_status=ParseStatus.FAILED,
        ).update(
            parse_status=ParseStatus.PENDING,
            parse_error='',
            parsed_at=None,
        )

        reparsed_count = reset_qs.filter(
            parse_status=ParseStatus.PARSED,
        ).update(
            parse_status=ParseStatus.PENDING,
            parse_error='',
        )

        if reset_count or reparsed_count:
            self.stdout.write(
                f"Reset: {reset_count} failed + "
                f"{reparsed_count} parsed -> pending"
            )

        # 6. Create audit SyncRun
        run = SyncRun.objects.create(
            integration_account=account,
            resource_type=resource,
            mode='reprocess',
            meta={
                'reprocess_statuses': statuses,
                'target_count': effective_count,
                'bulk_mode': bulk,
            },
        )

        # 7. Re-query pending rows and process
        if limit:
            pending_qs = RawPayload.objects.filter(
                pk__in=target_pks,
                parse_status=ParseStatus.PENDING,
            ).order_by('fetched_at')
        else:
            pending_qs = RawPayload.objects.filter(
                integration_account=account,
                resource_type=resource,
                parse_status=ParseStatus.PENDING,
            ).order_by('fetched_at')

        t0 = time.monotonic()

        if bulk:
            processed = self._process_bulk(
                pending_qs, service, run, batch_size, effective_count,
            )
        else:
            processed = self._process_sequential(
                pending_qs, service, run,
            )

        elapsed = time.monotonic() - t0
        run.processed_count = processed
        run.finish(SyncRunStatus.COMPLETED)

        # 8. Clean up caches
        if bulk:
            self._clear_caches()

        # 9. Report
        rate = processed / elapsed if elapsed > 0 else 0
        self.stdout.write(self.style.SUCCESS(
            f"Reprocess complete (SyncRun {run.pk}): "
            f"processed={run.processed_count} "
            f"created={run.created_count} "
            f"updated={run.updated_count} "
            f"errors={run.error_count} "
            f"elapsed={elapsed:.1f}s ({rate:.0f} rows/s)"
        ))

    # ── Bulk processing ───────────────────────────────────────────────

    def _process_bulk(self, pending_qs, service, run, batch_size, total):
        """Process in transaction batches with progress reporting."""
        processed = 0
        batch = []

        for raw in pending_qs.iterator():
            batch.append(raw)

            if len(batch) >= batch_size:
                self._process_batch(batch, service, run)
                processed += len(batch)
                batch = []

                # Progress report
                pct = (processed / total * 100) if total else 0
                self.stdout.write(
                    f"  [{processed:,}/{total:,}] {pct:.0f}% "
                    f"(created={run.created_count} "
                    f"updated={run.updated_count} "
                    f"errors={run.error_count})"
                )

        # Final partial batch
        if batch:
            self._process_batch(batch, service, run)
            processed += len(batch)

        return processed

    def _process_batch(self, batch, service, run):
        """Process a batch of raw payloads within a single transaction."""
        with transaction.atomic():
            for raw in batch:
                service._try_parse(raw, run)

            run.save(update_fields=[
                'processed_count', 'created_count',
                'updated_count', 'error_count', 'updated_at',
            ])

    # ── Sequential processing (original) ──────────────────────────────

    def _process_sequential(self, pending_qs, service, run):
        """Original row-by-row processing."""
        processed = 0
        for raw in pending_qs.iterator():
            service._try_parse(raw, run)
            processed += 1

            if processed % 100 == 0:
                run.save(update_fields=[
                    'processed_count', 'created_count',
                    'updated_count', 'error_count', 'updated_at',
                ])

        return processed

    # ── Cache management ──────────────────────────────────────────────

    def _warm_caches(self, resource):
        from apps.inventory.services import warm_game_cache
        from apps.sync.services.shared.owned_product import warm_owned_product_cache

        game_count = warm_game_cache()
        self.stdout.write(f"Warmed game cache: {game_count} mappings")

        if resource in (ResourceType.ORDERS, ResourceType.OWNED_PRODUCTS):
            owned_count = warm_owned_product_cache()
            self.stdout.write(f"Warmed owned_product cache: {owned_count} records")

    def _clear_caches(self):
        from apps.inventory.services import clear_game_cache
        from apps.sync.services.shared.owned_product import clear_owned_product_cache

        clear_game_cache()
        clear_owned_product_cache()
