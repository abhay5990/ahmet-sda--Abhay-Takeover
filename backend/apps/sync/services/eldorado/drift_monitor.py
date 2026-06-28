"""Eldorado Drift Monitor — detects and corrects listing count drift.

Compares remote offer counts (via stateCount API) with local DB counts
for variant-managed games (FN/VAL/R6). When drift exceeds a threshold,
triggers a mini sync to reconcile.

Designed to run 3-4 times per day via management command + cron.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.inventory.models import Game, GamePlatformMapping
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import GameVariant, GameVariantMapping
from apps.posting.services.variant_slug import build_composite_variant
from apps.sync.enums import SyncLogLevel
from apps.sync.models import SyncLog

logger = logging.getLogger(__name__)

# Games with variant management on Eldorado
VARIANT_GAMES = ['fortnite', 'valorant', 'rainbow-six-siege']

# Drift thresholds
DRIFT_THRESHOLD = 5
ALERT_THRESHOLD = 20

# Grace period: listings updated within this window are excluded from stale check
STALE_GRACE_HOURS = 6

# Log retention
LOG_RETENTION_DAYS = 15

# Eldorado search page size
_PAGE_SIZE = 40


def run_drift_check(
    *,
    dry_run: bool = False,
    threshold_override: int | None = None,
    store_slug: str | None = None,
    game_slug: str | None = None,
) -> dict[str, Any]:
    """Run drift check for all active Eldorado stores and variant games.

    Args:
        dry_run: If True, only report drift without triggering mini sync.
        threshold_override: Override DRIFT_THRESHOLD (e.g. 0 for --force).
        store_slug: Filter to a specific store.
        game_slug: Filter to a specific game.

    Returns summary dict with total checks and actions taken.
    """
    # Cleanup old logs first (skip in dry-run)
    if not dry_run:
        _cleanup_old_logs()

    filters = {
        'provider': 'eldorado',
        'is_active': True,
        'credential__is_active': True,
    }
    if store_slug:
        filters['slug'] = store_slug

    stores = IntegrationAccount.objects.select_related('credential').filter(**filters)

    summary: dict[str, Any] = {'checks': 0, 'mini_syncs': 0, 'errors': 0, 'details': []}

    effective_threshold = threshold_override if threshold_override is not None else DRIFT_THRESHOLD
    games_filter = [game_slug] if game_slug else None

    for store in stores:
        try:
            _check_store(
                store, summary,
                dry_run=dry_run,
                threshold=effective_threshold,
                games_filter=games_filter,
            )
        except Exception as exc:
            logger.exception("Drift check failed for store %s: %s", store.name, exc)
            summary['errors'] += 1
            if not dry_run:
                SyncLog.objects.create(
                    task_name='drift_monitor',
                    level=SyncLogLevel.ERROR,
                    message=f"Drift check error: {store.name}",
                    detail={'error': str(exc)},
                    integration_account=store,
                )

    return summary


def _check_store(
    store: IntegrationAccount,
    summary: dict,
    *,
    dry_run: bool = False,
    threshold: int = DRIFT_THRESHOLD,
    games_filter: list[str] | None = None,
) -> None:
    """Check all variant games for a single store."""
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    provider = get_provider('eldorado')
    client = get_or_build_client(
        'eldorado', store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    check_games = games_filter if games_filter else VARIANT_GAMES

    for game_slug in check_games:
        try:
            game = Game.objects.get(slug=game_slug)
        except Game.DoesNotExist:
            continue

        # Get game's Eldorado external ID (for stateCount API filtering)
        try:
            game_mapping = GamePlatformMapping.objects.get(
                game=game, platform='eldorado',
            )
        except GamePlatformMapping.DoesNotExist:
            continue

        game_ext_id = game_mapping.external_id

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
                    _check_variant(
                        store=store,
                        game=game,
                        variant_slug=build_composite_variant({
                            'region': region_mapping.variant.slug,
                            'platform': platform_mapping.variant.slug,
                        }),
                        trade_environment_id=(
                            f"{region_mapping.external_id}-"
                            f"{platform_mapping.external_id}"
                        ),
                        game_ext_id=game_ext_id,
                        client=client,
                        provider=provider,
                        summary=summary,
                        dry_run=dry_run,
                        threshold=threshold,
                    )
            continue

        for mapping in platform_mappings or region_mappings:
            _check_variant(
                store=store,
                game=game,
                variant_slug=mapping.variant.slug,
                trade_environment_id=mapping.external_id,
                game_ext_id=game_ext_id,
                client=client,
                provider=provider,
                summary=summary,
                dry_run=dry_run,
                threshold=threshold,
            )


def _check_variant(
    *,
    store: IntegrationAccount,
    game: Game,
    variant_slug: str,
    trade_environment_id: str,
    game_ext_id: str,
    client: Any,
    provider: Any,
    summary: dict,
    dry_run: bool = False,
    threshold: int = DRIFT_THRESHOLD,
) -> None:
    """Check drift for a single store + game + variant combination."""
    summary['checks'] += 1

    # Remote count via stateCount API
    result = client.get_offer_state_counts(
        params={
            'gameId': game_ext_id,
            'tradeEnvironmentId': trade_environment_id,
        },
    )

    if not result.ok:
        logger.warning(
            "stateCount API failed for %s/%s/%s: %s",
            store.name, game.slug, variant_slug,
            result.error.message if result.error else 'unknown',
        )
        return

    remote_active = result.data.activeOffers

    # Local count
    local_active = Listing.objects.filter(
        integration_account=store,
        game=game,
        variant=variant_slug,
        status=ListingStatus.LISTED,
    ).count()

    drift = remote_active - local_active

    # Collect details for dry-run output
    summary.setdefault('details', []).append({
        'store': store.name,
        'game': game.slug,
        'variant': variant_slug,
        'trade_environment_id': trade_environment_id,
        'remote': remote_active,
        'local': local_active,
        'drift': drift,
    })

    # Log every check (skip in dry-run)
    if not dry_run:
        SyncLog.objects.create(
            task_name='drift_monitor',
            level=SyncLogLevel.WARNING if abs(drift) > ALERT_THRESHOLD else SyncLogLevel.INFO,
            message=(
                f"Drift check: {store.name} / {game.slug} / {variant_slug} — "
                f"remote={remote_active}, local={local_active}, drift={drift:+d}"
            ),
            detail={
                'game': game.slug,
                'variant': variant_slug,
                'trade_environment_id': trade_environment_id,
                'remote_active': remote_active,
                'local_active': local_active,
                'drift': drift,
                'action': 'mini_sync' if abs(drift) > threshold else 'none',
            },
            integration_account=store,
        )

    if dry_run:
        return

    if abs(drift) > threshold:
        _run_mini_sync(
            store=store,
            game=game,
            variant_slug=variant_slug,
            trade_environment_id=trade_environment_id,
            game_ext_id=game_ext_id,
            client=client,
            provider=provider,
            summary=summary,
        )


def _run_mini_sync(
    *,
    store: IntegrationAccount,
    game: Game,
    variant_slug: str,
    trade_environment_id: str,
    game_ext_id: str,
    client: Any,
    provider: Any,
    summary: dict,
) -> None:
    """Fetch all Active offers for a variant and reconcile with DB."""
    from apps.sync.services.eldorado.offers.service import EldoradoOfferSyncService
    from apps.sync.models import RawPayload
    from apps.sync.enums import ResourceType, ParseStatus

    summary['mini_syncs'] += 1
    sync_service = EldoradoOfferSyncService(provider=provider, client=client)

    # Fetch all Active offers in a single pass — collect both IDs and payloads
    remote_offers: dict[str, dict] = {}  # offer_id → offer_dict
    page = 1
    pages_fetched = 0

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
            logger.warning(
                "Mini sync fetch failed at page %d for %s/%s/%s",
                page, store.name, game.slug, variant_slug,
            )
            break

        pages_fetched += 1
        page_data = result.data

        for offer in page_data.results:
            offer_dict = offer.model_dump() if hasattr(offer, 'model_dump') else dict(offer)
            offer_id = str(offer_dict.get('id', ''))
            if offer_id:
                remote_offers[offer_id] = offer_dict

        # Check if more pages
        if page_data.pageIndex >= page_data.totalPages:
            break
        page += 1

    remote_offer_ids = set(remote_offers.keys())

    # --- Reconcile ---

    # 1. Find offers that are Active on remote but not LISTED in DB.
    #    This covers both genuinely new offers AND offers that exist in DB
    #    with a wrong status (paused/deleted/closed) — both need parse_and_apply.
    listed_ids = set(
        Listing.objects.filter(
            integration_account=store,
            game=game,
            variant=variant_slug,
            status=ListingStatus.LISTED,
            store_listing_id__in=remote_offer_ids,
        ).values_list('store_listing_id', flat=True)
    )
    to_apply_ids = remote_offer_ids - listed_ids
    added = 0

    for offer_id in to_apply_ids:
        offer_dict = remote_offers[offer_id]

        # Enrich with credentials
        enriched, _meta = sync_service.prepare_item(offer_dict, store)

        payload_bytes = json.dumps(enriched, default=str).encode()
        now = timezone.now()

        raw, _created = RawPayload.objects.update_or_create(
            integration_account=store,
            resource_type=ResourceType.LISTINGS,
            remote_id=offer_id,
            defaults={
                'payload': enriched,
                'payload_hash': hashlib.sha256(payload_bytes).hexdigest(),
                'first_seen_at': now,
                'last_seen_at': now,
                'fetched_at': now,
                'parse_status': ParseStatus.PENDING,
            },
        )

        try:
            sync_service.parse_and_apply(raw)
            raw.parse_status = ParseStatus.PARSED
            raw.save(update_fields=['parse_status'])
            added += 1
        except Exception as exc:
            logger.warning(
                "Mini sync parse failed for offer %s: %s",
                offer_id, exc,
            )

    # 2. Find stale listings (DB has LISTED, remote doesn't)
    grace_cutoff = timezone.now() - timedelta(hours=STALE_GRACE_HOURS)
    stale_listings = Listing.objects.filter(
        integration_account=store,
        game=game,
        variant=variant_slug,
        status=ListingStatus.LISTED,
    ).exclude(
        store_listing_id__in=remote_offer_ids,
    ).exclude(
        updated_at__gte=grace_cutoff,
    )

    # Collect DP IDs before bulk update (signal won't fire)
    stale_dp_ids = set(
        stale_listings.filter(dropship_product__isnull=False)
        .values_list('dropship_product_id', flat=True)
    )
    deleted = stale_listings.update(status=ListingStatus.DELETED)
    # Cascade to orphaned DropshipProducts
    if stale_dp_ids:
        from apps.sync.services.base import _reconcile_dropship_products
        _reconcile_dropship_products(stale_dp_ids)

    # Log result
    SyncLog.objects.create(
        task_name='drift_monitor',
        level=SyncLogLevel.WARNING if (added + deleted) > ALERT_THRESHOLD else SyncLogLevel.INFO,
        message=(
            f"Mini sync completed: {store.name} / {game.slug} / {variant_slug} — "
            f"added={added}, deleted={deleted}"
        ),
        detail={
            'game': game.slug,
            'variant': variant_slug,
            'trade_environment_id': trade_environment_id,
            'offers_added': added,
            'offers_deleted': deleted,
            'pages_fetched': pages_fetched,
            'to_apply_ids_count': len(to_apply_ids),
        },
        integration_account=store,
    )

    logger.info(
        "Mini sync %s/%s/%s: added=%d deleted=%d pages=%d",
        store.name, game.slug, variant_slug, added, deleted, pages_fetched,
    )


def _cleanup_old_logs() -> None:
    """Delete drift_monitor logs older than LOG_RETENTION_DAYS."""
    cutoff = timezone.now() - timedelta(days=LOG_RETENTION_DAYS)
    deleted, _ = SyncLog.objects.filter(
        task_name='drift_monitor',
        created_at__lt=cutoff,
    ).delete()
    if deleted:
        logger.info("Cleaned up %d old drift_monitor logs", deleted)
