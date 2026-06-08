"""Management command: diagnose Eldorado drift for a single variant (read-only).

Fetches all remote Active offers for one store/game/variant and classifies each
against the local DB to answer: are the drifting offers GENUINELY MISSING, or do
they exist in the DB with a different status (paused/closed/deleted)?

Usage:
    python manage.py diagnose_eldorado_drift --store store4gamers --game fortnite --variant pc
    python manage.py diagnose_eldorado_drift --store store4gamers --game fortnite --variant pc --show-ids

Read-only: never writes to the DB or remote. Pure investigation.
"""

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.inventory.models import Game, GamePlatformMapping
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import GameVariant, GameVariantMapping
from apps.posting.services.variant_slug import build_composite_variant

_PAGE_SIZE = 40


class Command(BaseCommand):
    help = 'Diagnose Eldorado drift for one variant: missing vs status-mismatch.'

    def add_arguments(self, parser):
        parser.add_argument('--store', required=True, help='Store slug.')
        parser.add_argument('--game', required=True, help='Game slug (e.g. fortnite).')
        parser.add_argument('--variant', required=True, help='Variant slug (e.g. pc, eu-psn).')
        parser.add_argument(
            '--show-ids', action='store_true',
            help='Print the offending offer IDs (missing + status-mismatch).',
        )

    def handle(self, *args, **options):
        store_slug = options['store']
        game_slug = options['game']
        variant_slug = options['variant']
        show_ids = options['show_ids']

        try:
            store = IntegrationAccount.objects.select_related('credential').get(
                provider='eldorado', slug=store_slug,
            )
        except IntegrationAccount.DoesNotExist:
            raise CommandError(f"Store not found: {store_slug}")

        try:
            game = Game.objects.get(slug=game_slug)
        except Game.DoesNotExist:
            raise CommandError(f"Game not found: {game_slug}")

        try:
            game_ext_id = GamePlatformMapping.objects.get(
                game=game, platform='eldorado',
            ).external_id
        except GamePlatformMapping.DoesNotExist:
            raise CommandError(f"No eldorado GamePlatformMapping for game {game_slug}")

        trade_environment_id = self._resolve_trade_env_id(game, variant_slug)
        if not trade_environment_id:
            raise CommandError(
                f"Could not resolve tradeEnvironmentId for {game_slug}/{variant_slug}"
            )

        self.stdout.write(
            f"Diagnosing {store.name}/{game_slug}/{variant_slug} "
            f"(gameId={game_ext_id}, tradeEnvId={trade_environment_id})..."
        )

        # --- Build client ---
        proxy_pool = build_proxy_pool()
        provider = get_provider('eldorado')
        client = get_or_build_client(
            'eldorado', store.credential,
            proxy_pool=proxy_pool,
            proxy_group=get_group_name(store),
        )

        # --- Fetch all remote Active offer IDs ---
        remote_ids = self._fetch_remote_offer_ids(
            client, game_ext_id, trade_environment_id,
        )
        if remote_ids is None:
            raise CommandError("Remote fetch failed (see warnings above).")

        # --- Local listings for those remote IDs (ALL statuses) ---
        local_rows = Listing.objects.filter(
            integration_account=store,
            game=game,
            variant=variant_slug,
            store_listing_id__in=remote_ids,
        ).values_list('store_listing_id', 'status')
        local_status_by_id = {sid: status for sid, status in local_rows}

        # Local LISTED count for this variant (matches drift_monitor's "local")
        local_listed_total = Listing.objects.filter(
            integration_account=store,
            game=game,
            variant=variant_slug,
            status=ListingStatus.LISTED,
        ).count()

        # --- Classify each remote offer ---
        genuinely_missing = []   # remote Active, no DB row at all
        status_mismatch = []     # remote Active, DB row exists but status != LISTED
        mismatch_status_counts = Counter()
        ok_listed = 0

        for rid in remote_ids:
            status = local_status_by_id.get(rid)
            if status is None:
                genuinely_missing.append(rid)
            elif status != ListingStatus.LISTED:
                status_mismatch.append(rid)
                mismatch_status_counts[status] += 1
            else:
                ok_listed += 1

        # Reverse direction: LISTED locally for this variant but not in remote Active.
        local_listed_ids = set(
            Listing.objects.filter(
                integration_account=store,
                game=game,
                variant=variant_slug,
                status=ListingStatus.LISTED,
            ).values_list('store_listing_id', flat=True)
        )
        extra_local = local_listed_ids - set(remote_ids)

        # --- Report ---
        remote_total = len(remote_ids)
        drift = remote_total - local_listed_total

        self.stdout.write("\n--- Drift Diagnosis ---")
        self.stdout.write(f"  remote Active offers : {remote_total}")
        self.stdout.write(f"  local LISTED count   : {local_listed_total}")
        self.stdout.write(f"  drift (remote-local) : {drift:+d}")
        self.stdout.write("")
        self.stdout.write(f"  remote offers matched LISTED in DB : {ok_listed}")
        self.stdout.write(self.style.WARNING(
            f"  GENUINELY MISSING (no DB row)      : {len(genuinely_missing)}"
        ))
        self.stdout.write(self.style.WARNING(
            f"  STATUS MISMATCH (DB row not LISTED): {len(status_mismatch)}"
        ))
        for status, cnt in sorted(mismatch_status_counts.items()):
            self.stdout.write(f"      └─ {status}: {cnt}")
        self.stdout.write(
            f"  LISTED locally but NOT in remote   : {len(extra_local)}"
        )

        # Sanity hint
        self.stdout.write("")
        if status_mismatch and not genuinely_missing:
            self.stdout.write(self.style.SUCCESS(
                "  → Drift is purely a STATUS problem (offers exist, wrong status). "
                "A mini sync (parse_and_apply) will flip them back to LISTED."
            ))
        elif genuinely_missing and not status_mismatch:
            self.stdout.write(self.style.SUCCESS(
                "  → Drift is genuinely MISSING offers (never ingested). "
                "A mini sync will create them."
            ))
        elif genuinely_missing and status_mismatch:
            self.stdout.write(
                "  → Mixed: some offers missing, some have the wrong status."
            )

        if show_ids:
            if genuinely_missing:
                self.stdout.write("\n  Missing offer IDs:")
                for rid in sorted(genuinely_missing):
                    self.stdout.write(f"    {rid}")
            if status_mismatch:
                self.stdout.write("\n  Status-mismatch offer IDs (id: db_status):")
                for rid in sorted(status_mismatch):
                    self.stdout.write(f"    {rid}: {local_status_by_id[rid]}")
            if extra_local:
                self.stdout.write("\n  LISTED-locally-but-not-remote IDs:")
                for rid in sorted(extra_local):
                    self.stdout.write(f"    {rid}")

    def _resolve_trade_env_id(self, game: Game, variant_slug: str) -> str | None:
        """Resolve the Eldorado tradeEnvironmentId for a variant slug.

        Mirrors drift_monitor: composite region-platform variants combine two
        external IDs; platform-only / region-only variants use a single mapping.
        """
        platform_mappings = list(GameVariantMapping.objects.select_related('variant').filter(
            variant__game=game,
            variant__type=GameVariant.VariantType.PLATFORM,
            marketplace='eldorado',
        ))
        region_mappings = list(GameVariantMapping.objects.select_related('variant').filter(
            variant__game=game,
            variant__type=GameVariant.VariantType.REGION,
            marketplace='eldorado',
        ))

        if region_mappings and platform_mappings:
            for region_mapping in region_mappings:
                for platform_mapping in platform_mappings:
                    composite = build_composite_variant({
                        'region': region_mapping.variant.slug,
                        'platform': platform_mapping.variant.slug,
                    })
                    if composite == variant_slug:
                        return f"{region_mapping.external_id}-{platform_mapping.external_id}"
            return None

        for mapping in platform_mappings or region_mappings:
            if mapping.variant.slug == variant_slug:
                return mapping.external_id
        return None

    def _fetch_remote_offer_ids(
        self, client, game_ext_id: str, trade_environment_id: str,
    ) -> set[str] | None:
        """Page through search_my_offers (Active) and collect offer IDs."""
        remote_ids: set[str] = set()
        page = 1
        while True:
            result = client.search_my_offers(
                params={
                    'offerState': 'Active',
                    'gameId': game_ext_id,
                    'tradeEnvironmentId': trade_environment_id,
                    'pageIndex': page,
                    'pageSize': _PAGE_SIZE,
                },
            )
            if not result.ok or result.data is None:
                self.stderr.write(
                    f"  Remote fetch failed at page {page}: "
                    f"{result.error.message if result.error else 'unknown'}"
                )
                return None

            page_data = result.data
            for offer in page_data.results:
                offer_dict = offer.model_dump() if hasattr(offer, 'model_dump') else dict(offer)
                offer_id = str(offer_dict.get('id', ''))
                if offer_id:
                    remote_ids.add(offer_id)

            if page_data.pageIndex >= page_data.totalPages:
                break
            page += 1

        return remote_ids
