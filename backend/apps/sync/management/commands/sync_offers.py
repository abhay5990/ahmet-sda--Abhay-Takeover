from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import IntegrationAccount
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.sync.enums import CheckpointStatus, ResourceType, SyncMode, SyncPhase
from apps.sync.exceptions import StopSync
from apps.sync.models import SyncCheckpoint
from apps.sync.services.registry import (
    build_service,
    get_service_class,
    get_providers_for_resource,
)


class Command(BaseCommand):
    help = 'Sync marketplace offers/listings from a provider into the local database.'

    def add_arguments(self, parser):
        parser.add_argument(
            'account',
            type=str,
            help='IntegrationAccount slug (e.g. "gameboost-store4gamers")',
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=[m.value for m in SyncMode],
            default=SyncMode.INCREMENTAL,
            help=(
                'Sync mode: backfill (full history) or '
                'incremental (from last checkpoint)'
            ),
        )
        parser.add_argument(
            '--phase',
            type=str,
            choices=[p.value for p in SyncPhase],
            default=SyncPhase.FULL,
            help=(
                'Sync phase: full (ingest+process), '
                'ingest (fetch+persist only), '
                'process (parse pending raws only)'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate setup without actually syncing',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset completed backfill checkpoint before running',
        )

    def handle(self, *args, **options):
        slug = options['account']
        mode = options['mode']
        phase = options['phase']
        dry_run = options['dry_run']
        reset = options['reset']
        resource = ResourceType.LISTINGS

        # 1. Account lookup
        try:
            account = IntegrationAccount.objects.select_related(
                'credential',
            ).get(slug=slug, is_active=True)
        except IntegrationAccount.DoesNotExist:
            raise CommandError(
                f'Active IntegrationAccount with slug "{slug}" not found.'
            )

        if (
            not hasattr(account, 'credential')
            or not account.credential.is_active
        ):
            raise CommandError(
                f'Account "{slug}" has no active credentials.'
            )

        # 2. Resolve sync service
        service_class = get_service_class(resource, account.provider)
        if service_class is None:
            supported = get_providers_for_resource(resource)
            raise CommandError(
                f'No sync service registered for '
                f'({resource}, "{account.provider}"). '
                f'Supported providers for {resource}: '
                f'{", ".join(supported) or "none"}'
            )

        # 3. Build service (provider + client from credential + proxy)
        proxy_pool = build_proxy_pool()
        proxy_group = get_group_name(account)
        try:
            service = build_service(
                resource, account.provider, credential=account.credential,
                proxy_pool=proxy_pool, proxy_group=proxy_group,
            )
        except Exception as exc:
            raise CommandError(
                f'Failed to build service for "{slug}": {exc}'
            )

        self.stdout.write(
            f"Sync offers: account={account.slug} "
            f"provider={account.provider} resource={resource} "
            f"mode={mode} phase={phase}"
        )
        if proxy_pool and proxy_group:
            group_count = len(proxy_pool.get_all(group=proxy_group))
            self.stdout.write(f"Proxy: group={proxy_group} ({group_count} proxies)")
        else:
            self.stdout.write(self.style.WARNING("Proxy: none — using direct IP"))

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS("Dry run — setup validated OK."),
            )
            return

        # 4. Reset checkpoint if requested
        if reset and mode == SyncMode.BACKFILL:
            updated = SyncCheckpoint.objects.filter(
                integration_account=account,
                resource_type=resource,
                mode=SyncMode.BACKFILL,
                status=CheckpointStatus.COMPLETED,
            ).update(
                status=CheckpointStatus.ACTIVE,
                cursor='',
                last_seen_remote_id='',
                last_seen_remote_timestamp=None,
                meta={},
            )
            if updated:
                self.stdout.write(self.style.WARNING(
                    "Backfill checkpoint reset."
                ))

        # 5. Run sync
        try:
            run = service.run(account, mode=mode, phase=phase)
        except StopSync as exc:
            raise CommandError(f"Sync stopped: {exc.message}")
        except NotImplementedError as exc:
            raise CommandError(str(exc))

        if run is None:
            self.stdout.write(self.style.WARNING(
                "Backfill already completed for this account. "
                "Reset the checkpoint to re-run."
            ))
            return

        # 5. Report results
        self.stdout.write(self.style.SUCCESS(
            f"SyncRun {run.pk} finished: status={run.status} "
            f"processed={run.processed_count} created={run.created_count} "
            f"updated={run.updated_count} errors={run.error_count}"
        ))
