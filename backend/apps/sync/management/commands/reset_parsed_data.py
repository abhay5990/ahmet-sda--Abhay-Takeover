"""Reset parsed domain data and re-parse from RawPayload.

Deletes rows from the target table, resets RawPayload status to pending,
then optionally re-parses. Useful after model/mapper changes.

Usage:
    python manage.py reset_parsed_data <account-slug> --resource owned_products
    python manage.py reset_parsed_data --all --resource owned_products
    python manage.py reset_parsed_data --all --resource owned_products --reparse
    python manage.py reset_parsed_data <account-slug> --resource owned_products --dry-run
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.models import IntegrationAccount
from apps.sync.enums import ParseStatus, ResourceType, SyncMode, SyncRunStatus
from apps.sync.models import RawPayload, SyncRun

# Resource type → (model class, delete filter builder)
RESOURCE_MAP = {
    ResourceType.OWNED_PRODUCTS: 'apps.inventory.models.OwnedProduct',
}


def _get_model(resource_type):
    """Lazy import to avoid circular imports."""
    path = RESOURCE_MAP.get(resource_type)
    if not path:
        return None
    module_path, class_name = path.rsplit('.', 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _get_service(resource_type, provider_name):
    """Get a sync service instance via the registry (parse-only, no client)."""
    from apps.sync.services.registry import build_service
    try:
        return build_service(resource_type, provider_name)
    except LookupError:
        return None


class Command(BaseCommand):
    help = 'Delete parsed domain data and reset RawPayload status for re-parsing.'

    def add_arguments(self, parser):
        parser.add_argument(
            'account',
            nargs='?',
            type=str,
            default=None,
            help='IntegrationAccount slug (omit if using --all)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            dest='reset_all',
            help='Reset ALL accounts (no account slug needed)',
        )
        parser.add_argument(
            '--resource',
            type=str,
            choices=[r.value for r in ResourceType],
            required=True,
            help='Resource type to reset',
        )
        parser.add_argument(
            '--reparse',
            action='store_true',
            help='Also re-parse after resetting (otherwise just reset)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Batch size for re-parse (default: 500)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would happen without doing it',
        )

    def handle(self, *args, **options):
        slug = options['account']
        reset_all = options['reset_all']
        resource = options['resource']
        reparse = options['reparse']
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        if not slug and not reset_all:
            raise CommandError(
                'Provide an account slug or use --all to reset all accounts.'
            )
        if slug and reset_all:
            raise CommandError(
                'Cannot use both account slug and --all together.'
            )

        # 1. Account lookup
        account = None
        if slug:
            try:
                account = IntegrationAccount.objects.get(slug=slug, is_active=True)
            except IntegrationAccount.DoesNotExist:
                raise CommandError(
                    f'Active IntegrationAccount with slug "{slug}" not found.'
                )

        # 2. Get target model
        model = _get_model(resource)
        if model is None:
            raise CommandError(
                f'No domain model mapped for resource "{resource}". '
                f'Supported: {", ".join(RESOURCE_MAP.keys())}'
            )

        # 3. Build querysets based on scope
        if account:
            domain_qs = model.objects.filter(source_account=account)
            raw_qs = RawPayload.objects.filter(
                integration_account=account,
                resource_type=resource,
            )
            scope_label = f'Account: {slug}'
        else:
            domain_qs = model.objects.all()
            raw_qs = RawPayload.objects.filter(resource_type=resource)
            scope_label = 'Account: ALL'

        domain_count = domain_qs.count()
        raw_count = raw_qs.count()
        parsed_count = raw_qs.filter(parse_status=ParseStatus.PARSED).count()

        self.stdout.write(
            f'{scope_label}\n'
            f'Resource: {resource}\n'
            f'Domain rows to delete: {domain_count:,}\n'
            f'RawPayload total: {raw_count:,}\n'
            f'RawPayload parsed → pending: {parsed_count:,}'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run — no changes made.'))
            return

        # 4. Confirm
        self.stdout.write(
            self.style.WARNING(
                f'\nThis will DELETE {domain_count:,} {model.__name__} rows '
                f'and reset {parsed_count:,} RawPayloads to pending.'
            )
        )
        confirm = input('Type "yes" to confirm: ')
        if confirm.strip().lower() != 'yes':
            self.stdout.write('Aborted.')
            return

        # 5. Delete domain rows
        start = time.time()
        deleted, _ = domain_qs.delete()
        self.stdout.write(f'Deleted {deleted:,} {model.__name__} rows.')

        # 6. Reset RawPayload statuses
        reset_count = raw_qs.exclude(
            parse_status=ParseStatus.PENDING,
        ).update(
            parse_status=ParseStatus.PENDING,
            parse_error='',
            parsed_at=None,
        )
        self.stdout.write(f'Reset {reset_count:,} RawPayloads to pending.')

        # 7. Optional reparse
        if not reparse:
            elapsed = time.time() - start
            self.stdout.write(self.style.SUCCESS(
                f'Done in {elapsed:.1f}s. Run with --reparse or use '
                f'"import_lzt_orders --phase full" to re-parse.'
            ))
            return

        # Reparse: if --all, create a SyncRun per account; otherwise single run
        pending_qs = raw_qs.filter(
            parse_status=ParseStatus.PENDING,
        ).order_by('fetched_at')

        if account:
            accounts = [account]
        else:
            account_ids = pending_qs.values_list(
                'integration_account', flat=True,
            ).distinct()
            accounts = list(IntegrationAccount.objects.filter(pk__in=account_ids))

        total_processed = 0

        for acct in accounts:
            acct_pending = pending_qs.filter(integration_account=acct)
            count = acct_pending.count()
            if count == 0:
                continue

            service = _get_service(resource, acct.provider)
            if service is None:
                self.stdout.write(self.style.WARNING(
                    f'No service for ({resource}, {acct.provider}). '
                    f'Skipping {acct.slug}.'
                ))
                continue

            run = SyncRun.objects.create(
                integration_account=acct,
                resource_type=resource,
                mode=SyncMode.BACKFILL,
                meta={'reparse_after_reset': True},
            )

            self.stdout.write(
                f'\nReparsing {count:,} items for {acct.slug} '
                f'(SyncRun {run.pk})...'
            )

            processed = 0
            batch_num = 0
            batch_items = []

            for raw in acct_pending.iterator():
                batch_items.append(raw)

                if len(batch_items) >= batch_size:
                    batch_num += 1
                    with transaction.atomic():
                        for item in batch_items:
                            service._try_parse(item, run)
                            processed += 1
                    batch_items = []

                    run.processed_count = processed
                    run.save(update_fields=[
                        'processed_count', 'created_count',
                        'updated_count', 'error_count', 'updated_at',
                    ])
                    elapsed = time.time() - start
                    rate = processed / elapsed if elapsed > 0 else 0
                    self.stdout.write(
                        f'  batch {batch_num}: {processed:,} parsed '
                        f'({rate:.0f}/s)'
                    )

            # Flush remaining
            if batch_items:
                with transaction.atomic():
                    for item in batch_items:
                        service._try_parse(item, run)
                        processed += 1

            run.processed_count = processed
            run.finish(SyncRunStatus.COMPLETED)
            total_processed += processed

            self.stdout.write(self.style.SUCCESS(
                f'  {acct.slug}: processed={run.processed_count:,} '
                f'created={run.created_count:,} '
                f'updated={run.updated_count:,} '
                f'errors={run.error_count:,}'
            ))

        elapsed = time.time() - start
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Reparse complete: {total_processed:,} total in {elapsed:.1f}s'
        ))
