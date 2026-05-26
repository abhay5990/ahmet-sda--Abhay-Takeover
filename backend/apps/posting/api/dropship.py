"""Dropship API endpoints — config CRUD, target URL management, scheduler control, stats."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount
from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct, Game
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import (
    CleanerConfig,
    DropshippingJobConfig,
    DropshipTargetURL,
    GameVariant,
    GameVariantLimit,
    PostingLog,
    SchedulerHeartbeat,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation limits
# ---------------------------------------------------------------------------

_CONFIG_LIMITS: dict[str, tuple[float, float]] = {
    'item_delay': (0.5, 300),
    'source_delay': (0.5, 300),
    'poster_cycle_interval': (30, 86400),
}

_URL_LIMITS: dict[str, tuple[float, float]] = {
    'multiplier_low': (1.2, 100),
    'multiplier_mid': (1.2, 100),
    'multiplier_high': (1.2, 100),
    'min_price': (0, 999999),
    'forced_ending': (0, 0.99),
}

_CLEANER_LIMITS: dict[str, tuple[float, float]] = {
    'cycle_interval': (60, 86400),
}


def _validate_numeric_fields(body: dict, limits: dict[str, tuple[float, float]]) -> str | None:
    """Return error message if any field in body violates its min/max limit."""
    for field, (lo, hi) in limits.items():
        if field not in body:
            continue
        try:
            val = float(body[field])
        except (TypeError, ValueError):
            return f"{field} must be a number"
        if val < lo or val > hi:
            return f"{field} must be between {lo} and {hi}"
    return None


def _check_config_ready(config: DropshippingJobConfig) -> str | None:
    """Return an error message if config is not ready to be enabled, else None.

    Guards:
    1. At least one enabled target URL must exist.
    2. If the game has platform variants, at least one GameVariantLimit must be configured.
    """
    has_urls = DropshipTargetURL.objects.filter(config=config, enabled=True).exists()
    if not has_urls:
        return 'Cannot enable: add at least one enabled target URL first'

    if GameVariant.objects.filter(game=config.game, type='platform').exists():
        has_limits = GameVariantLimit.objects.filter(
            store=config.store, variant__game=config.game,
        ).exists()
        if not has_limits:
            return (
                'Cannot enable: configure variant limits first '
                f'(game "{config.game.name}" requires variant selection)'
            )

    return None


@login_required
@require_GET
def dropship_configs(request):
    """List all dropship configs with their URLs + variant info."""
    configs = (
        DropshippingJobConfig.objects
        .select_related('source_account', 'store', 'game')
        .prefetch_related('target_urls')
        .order_by('-created_at')
    )

    # Pre-fetch platform variants + limits + active counts for all (store, game) pairs
    # to avoid N+1 queries inside the config loop.
    _all_game_ids = {c.game_id for c in configs}
    _platform_variants = list(
        GameVariant.objects
        .filter(game_id__in=_all_game_ids, type='platform')
        .order_by('game_id', 'sort_order')
    )
    variants_by_game: dict[int, list[GameVariant]] = {}
    for v in _platform_variants:
        variants_by_game.setdefault(v.game_id, []).append(v)

    variant_limits_map: dict[tuple[int, int], list[GameVariantLimit]] = {}
    active_counts_map: dict[tuple[int, int], dict[str, int]] = {}

    for c in configs:
        key = (c.store_id, c.game_id)
        if key not in variant_limits_map and c.game_id in variants_by_game:
            variant_limits_map[key] = list(
                GameVariantLimit.objects
                .filter(store_id=c.store_id, variant__game_id=c.game_id, variant__type='platform')
                .select_related('variant')
            )
            active_counts_map[key] = dict(
                Listing.objects.filter(
                    integration_account=c.store, game=c.game, status=ListingStatus.LISTED,
                )
                .values('variant')
                .annotate(count=Count('id'))
                .values_list('variant', 'count')
            )

    def _build_variant_info(config):
        game_variants = variants_by_game.get(config.game_id)
        if not game_variants:
            return {'has_variants': False}

        key = (config.store_id, config.game_id)
        limits = variant_limits_map.get(key, [])
        counts = active_counts_map.get(key, {})
        limits_by_slug = {lim.variant.slug: lim for lim in limits}

        return {
            'has_variants': True,
            'variant_limits': [
                {
                    'variant': v.slug,
                    'label': v.label,
                    'max_offers': limits_by_slug[v.slug].max_offers if v.slug in limits_by_slug else None,
                    'stock_reserve': limits_by_slug[v.slug].stock_reserve if v.slug in limits_by_slug else None,
                    'active': counts.get(v.slug, 0),
                }
                for v in game_variants
            ],
        }

    return JsonResponse({'configs': [
        {
            'id': c.id,
            'source_account': {'id': c.source_account.id, 'name': c.source_account.name},
            'store': {'id': c.store.id, 'name': c.store.name, 'provider': c.store.provider},
            'game': {'id': c.game.id, 'name': c.game.name, 'slug': c.game.slug},
            'enabled': c.enabled,
            'disabled_reason': c.disabled_reason,
            'poster_running': c.poster_running,
            'item_delay': str(c.item_delay),
            'source_delay': str(c.source_delay),
            'poster_cycle_interval': c.poster_cycle_interval,
            'poster_last_cycle_at': c.poster_last_cycle_at.isoformat() if c.poster_last_cycle_at else None,
            **_build_variant_info(c),
            'urls': [
                {
                    'id': u.id,
                    'url': u.url,
                    'enabled': u.enabled,
                    'multiplier_low': str(u.multiplier_low),
                    'multiplier_mid': str(u.multiplier_mid),
                    'multiplier_high': str(u.multiplier_high),
                    'min_price': str(u.min_price),
                    'forced_ending': str(u.forced_ending) if u.forced_ending is not None else None,
                    'last_fetched_at': u.last_fetched_at.isoformat() if u.last_fetched_at else None,
                    'last_error': u.last_error,
                    'items_found': u.items_found,
                    'items_posted': u.items_posted,
                }
                for u in c.target_urls.all()
            ],
        }
        for c in configs
    ]})


@login_required
@role_required('admin', 'user')
@require_POST
def create_dropship_config(request):
    """Create a new dropship config."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    source_account_id = body.get('source_account_id')
    store_id = body.get('store_id')
    game_id = body.get('game_id')

    if not all([source_account_id, store_id, game_id]):
        return JsonResponse(
            {'error': 'source_account_id, store_id, and game_id are required'},
            status=400,
        )

    try:
        source = IntegrationAccount.objects.get(id=source_account_id, is_active=True)
        store = IntegrationAccount.objects.get(
            id=store_id, is_active=True, role__in=['sell', 'both'],
        )
        game = Game.objects.get(id=game_id, is_active=True)
    except (IntegrationAccount.DoesNotExist, Game.DoesNotExist):
        return JsonResponse({'error': 'Account or game not found'}, status=404)

    err = _validate_numeric_fields(body, _CONFIG_LIMITS)
    if err:
        return JsonResponse({'error': err}, status=400)

    config, created = DropshippingJobConfig.objects.get_or_create(
        source_account=source, store=store, game=game,
        defaults={
            'item_delay': body.get('item_delay', 3.0),
            'source_delay': body.get('source_delay', 1.0),
        },
    )

    if not created:
        return JsonResponse({'error': 'Config already exists', 'id': config.id}, status=409)

    # Auto-create CleanerConfig for the source account if it doesn't exist
    CleanerConfig.objects.get_or_create(
        source_account=source,
        defaults={'enabled': True},
    )

    return JsonResponse({'id': config.id}, status=201)


@login_required
@role_required('admin', 'user')
def update_dropship_config(request, config_id):
    """PATCH a dropship config (enable/disable, delays)."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        config = DropshippingJobConfig.objects.get(id=config_id)
    except DropshippingJobConfig.DoesNotExist:
        return JsonResponse({'error': 'Config not found'}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    err = _validate_numeric_fields(body, _CONFIG_LIMITS)
    if err:
        return JsonResponse({'error': err}, status=400)

    # Guard: check prerequisites before enabling
    if 'enabled' in body and body['enabled']:
        config.refresh_from_db()
        ready_err = _check_config_ready(config)
        if ready_err:
            return JsonResponse({'error': ready_err}, status=400)

    update_fields = []
    for field in ('enabled', 'item_delay', 'source_delay', 'poster_cycle_interval'):
        if field in body:
            setattr(config, field, body[field])
            update_fields.append(field)

    # When re-enabling, clear the disabled reason
    if 'enabled' in body and body['enabled']:
        config.disabled_reason = ''
        update_fields.append('disabled_reason')

    if update_fields:
        config.save(update_fields=update_fields)

    return JsonResponse({'ok': True})


@login_required
@role_required('admin', 'user')
@require_POST
def create_dropship_url(request, config_id):
    """Add a new target URL to a config."""
    try:
        config = DropshippingJobConfig.objects.get(id=config_id)
    except DropshippingJobConfig.DoesNotExist:
        return JsonResponse({'error': 'Config not found'}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    url_str = body.get('url', '').strip()
    if not url_str:
        return JsonResponse({'error': 'url is required'}, status=400)

    err = _validate_numeric_fields(body, _URL_LIMITS)
    if err:
        return JsonResponse({'error': err}, status=400)

    target_url = DropshipTargetURL.objects.create(
        config=config,
        url=url_str,
        multiplier_low=body.get('multiplier_low', 2.0),
        multiplier_mid=body.get('multiplier_mid', 1.8),
        multiplier_high=body.get('multiplier_high', 1.5),
        min_price=body.get('min_price', 0),
        forced_ending=body.get('forced_ending', 0.99),
    )

    return JsonResponse({'id': target_url.id}, status=201)


@login_required
@role_required('admin', 'user')
def update_dropship_url(request, url_id):
    """PATCH a target URL (pricing, enable/disable)."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        target_url = DropshipTargetURL.objects.get(id=url_id)
    except DropshipTargetURL.DoesNotExist:
        return JsonResponse({'error': 'URL not found'}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    err = _validate_numeric_fields(body, _URL_LIMITS)
    if err:
        return JsonResponse({'error': err}, status=400)

    update_fields = []
    for field in ('enabled', 'url', 'multiplier_low', 'multiplier_mid',
                  'multiplier_high', 'min_price', 'forced_ending'):
        if field in body:
            setattr(target_url, field, body[field])
            update_fields.append(field)

    if update_fields:
        target_url.save(update_fields=update_fields)

    return JsonResponse({'ok': True})


@login_required
@role_required('admin', 'user')
def delete_dropship_url(request, url_id):
    """DELETE a target URL."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        target_url = DropshipTargetURL.objects.get(id=url_id)
    except DropshipTargetURL.DoesNotExist:
        return JsonResponse({'error': 'URL not found'}, status=404)

    target_url.delete()
    return JsonResponse({'ok': True})


@login_required
@role_required('admin', 'user')
def delete_dropship_config(request, config_id):
    """DELETE a dropship config and all its URLs (CASCADE)."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        config = DropshippingJobConfig.objects.get(id=config_id)
    except DropshippingJobConfig.DoesNotExist:
        return JsonResponse({'error': 'Config not found'}, status=404)

    if config.poster_running:
        # Disable first — scheduler will stop the thread, then user can delete
        config.enabled = False
        config.save(update_fields=['enabled'])
        return JsonResponse(
            {'error': 'Poster is running. Config has been disabled — wait for it to stop, then delete.'},
            status=409,
        )

    config.delete()
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Poster control (per config) — simplified: just toggle enabled
# ---------------------------------------------------------------------------

@login_required
@role_required('admin', 'user')
@require_POST
def poster_stop(request, config_id):
    """Disable a poster config (thread will stop at next cycle check)."""
    try:
        config = DropshippingJobConfig.objects.get(id=config_id)
    except DropshippingJobConfig.DoesNotExist:
        return JsonResponse({'error': 'Config not found'}, status=404)

    config.enabled = False
    config.save(update_fields=['enabled'])
    return JsonResponse({'status': 'disabled'})


@login_required
@role_required('admin', 'user')
@require_POST
def poster_resume(request, config_id):
    """Re-enable a disabled poster config."""
    try:
        config = DropshippingJobConfig.objects.get(id=config_id)
    except DropshippingJobConfig.DoesNotExist:
        return JsonResponse({'error': 'Config not found'}, status=404)

    if config.enabled:
        return JsonResponse({'error': 'Config is already enabled'}, status=400)

    # Guard: check prerequisites before resuming
    ready_err = _check_config_ready(config)
    if ready_err:
        return JsonResponse({'error': ready_err}, status=400)

    config.enabled = True
    config.disabled_reason = ''
    config.save(update_fields=['enabled', 'disabled_reason'])
    return JsonResponse({'status': 'enabled'})


# ---------------------------------------------------------------------------
# Cleaner control (per source account)
# ---------------------------------------------------------------------------

@login_required
@require_GET
def cleaner_configs(request):
    """List all cleaner configs."""
    configs = CleanerConfig.objects.select_related('source_account').order_by('id')
    return JsonResponse({'cleaners': [
        {
            'id': cc.id,
            'source_account': {'id': cc.source_account.id, 'name': cc.source_account.name},
            'enabled': cc.enabled,
            'disabled_reason': cc.disabled_reason,
            'running': cc.running,
            'cycle_interval': cc.cycle_interval,
            'last_cycle_at': cc.last_cycle_at.isoformat() if cc.last_cycle_at else None,
        }
        for cc in configs
    ]})


@login_required
@role_required('admin', 'user')
@require_POST
def cleaner_toggle(request, cleaner_id):
    """Toggle a cleaner's enabled state."""
    try:
        cc = CleanerConfig.objects.get(id=cleaner_id)
    except CleanerConfig.DoesNotExist:
        return JsonResponse({'error': 'Cleaner config not found'}, status=404)

    cc.enabled = not cc.enabled
    if cc.enabled:
        cc.disabled_reason = ''
    cc.save(update_fields=['enabled', 'disabled_reason'])

    return JsonResponse({'enabled': cc.enabled})


@login_required
@role_required('admin', 'user')
@require_POST
def cleaner_stop(request, cleaner_id):
    """Disable a cleaner."""
    try:
        cc = CleanerConfig.objects.get(id=cleaner_id)
    except CleanerConfig.DoesNotExist:
        return JsonResponse({'error': 'Cleaner config not found'}, status=404)

    cc.enabled = False
    cc.save(update_fields=['enabled'])
    return JsonResponse({'status': 'disabled'})


@login_required
@role_required('admin', 'user')
@require_POST
def cleaner_resume(request, cleaner_id):
    """Re-enable a disabled cleaner."""
    try:
        cc = CleanerConfig.objects.get(id=cleaner_id)
    except CleanerConfig.DoesNotExist:
        return JsonResponse({'error': 'Cleaner config not found'}, status=404)

    if cc.enabled:
        return JsonResponse({'error': 'Cleaner is already enabled'}, status=400)

    cc.enabled = True
    cc.disabled_reason = ''
    cc.save(update_fields=['enabled', 'disabled_reason'])
    return JsonResponse({'status': 'enabled'})


# ---------------------------------------------------------------------------
# Scheduler status + bulk stop
# ---------------------------------------------------------------------------

@login_required
@require_GET
def scheduler_status(request):
    """Return scheduler heartbeat, cleaner states, and all config poster states."""
    heartbeat = SchedulerHeartbeat.objects.filter(service_name='dropship').first()

    if not heartbeat:
        return JsonResponse({
            'scheduler_alive': False,
            'message': 'Scheduler heartbeat not found',
        })

    alive = heartbeat.last_seen >= timezone.now() - timedelta(seconds=60)

    configs = DropshippingJobConfig.objects.only(
        'id', 'enabled', 'disabled_reason', 'poster_running',
        'poster_last_cycle_at',
    ).order_by('id')

    cleaners = CleanerConfig.objects.select_related('source_account').only(
        'id', 'enabled', 'disabled_reason', 'running', 'last_cycle_at',
        'source_account__id', 'source_account__name',
    ).order_by('id')

    return JsonResponse({
        'scheduler_alive': alive,
        'last_seen': heartbeat.last_seen.isoformat(),
        'pid': heartbeat.pid,
        'started_at': heartbeat.started_at.isoformat() if heartbeat.started_at else None,
        'configs': [
            {
                'id': c.id,
                'enabled': c.enabled,
                'disabled_reason': c.disabled_reason,
                'poster_running': c.poster_running,
                'poster_last_cycle_at': c.poster_last_cycle_at.isoformat() if c.poster_last_cycle_at else None,
            }
            for c in configs
        ],
        'cleaners': [
            {
                'id': cc.id,
                'source_account': cc.source_account.name,
                'enabled': cc.enabled,
                'disabled_reason': cc.disabled_reason,
                'running': cc.running,
                'last_cycle_at': cc.last_cycle_at.isoformat() if cc.last_cycle_at else None,
            }
            for cc in cleaners
        ],
    })


@login_required
@role_required('admin', 'user')
@require_POST
def stop_all(request):
    """Stop all poster threads + all cleaners."""
    DropshippingJobConfig.objects.filter(enabled=True).update(enabled=False)
    CleanerConfig.objects.filter(enabled=True).update(enabled=False)

    return JsonResponse({'status': 'all_disabled'})


@login_required
@role_required('admin', 'user')
def dropship_item_action(request, item_id):
    """PATCH: change status of a single DropshipProduct (e.g. delete)."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        item = DropshipProduct.objects.get(id=item_id)
    except DropshipProduct.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    action = body.get('action')
    if action == 'delete':
        from apps.posting.services.dropship.delist import delist_single
        result = delist_single(item)
        if result.ok:
            return JsonResponse({'ok': True})
        return JsonResponse({'error': result.error}, status=422)

    return JsonResponse({'error': f'Unknown action: {action}'}, status=400)


@login_required
@role_required('admin', 'user')
@require_POST
def dropship_item_bulk_action(request):
    """Bulk action on multiple DropshipProducts."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    item_ids = body.get('ids', [])
    action = body.get('action')

    if not item_ids or not isinstance(item_ids, list):
        return JsonResponse({'error': 'ids must be a non-empty list'}, status=400)

    from apps.posting.services.dropship.delist import delist_bulk, BULK_DELIST_LIMIT

    if len(item_ids) > BULK_DELIST_LIMIT:
        return JsonResponse(
            {'error': f'Maximum {BULK_DELIST_LIMIT} items per bulk action'},
            status=400,
        )

    if action == 'delete':
        dps = list(DropshipProduct.objects.filter(id__in=item_ids))
        if not dps:
            return JsonResponse({'error': 'No items found'}, status=404)

        result = delist_bulk(dps)
        return JsonResponse({
            'ok': len(result.failed) == 0,
            'succeeded': result.succeeded,
            'failed': result.failed,
            'errors': {str(k): v for k, v in result.errors.items()},
        }, status=200 if not result.failed else 207)

    return JsonResponse({'error': f'Unknown action: {action}'}, status=400)


# ---------------------------------------------------------------------------
# Variant limits
# ---------------------------------------------------------------------------

@login_required
@require_GET
def variant_limits(request):
    """Return platform variant limits + active counts for a store×game pair."""
    store_id = request.GET.get('store_id')
    game_id = request.GET.get('game_id')

    if not store_id or not game_id:
        return JsonResponse({'error': 'store_id and game_id are required'}, status=400)

    try:
        store = IntegrationAccount.objects.get(id=store_id)
        game = Game.objects.get(id=game_id)
    except (IntegrationAccount.DoesNotExist, Game.DoesNotExist):
        return JsonResponse({'error': 'Store or game not found'}, status=404)

    game_variants = list(
        GameVariant.objects.filter(game=game, type='platform').order_by('sort_order')
    )
    limits = list(
        GameVariantLimit.objects
        .filter(store=store, variant__game=game, variant__type='platform')
        .select_related('variant')
    )
    counts: dict[str, int] = {}
    if game_variants:
        counts = dict(
            Listing.objects
            .filter(integration_account=store, game=game, status=ListingStatus.LISTED)
            .values('variant')
            .annotate(count=Count('id'))
            .values_list('variant', 'count')
        )

    limits_by_slug = {lim.variant.slug: lim for lim in limits}

    return JsonResponse({
        'has_variants': bool(game_variants),
        'available_variants': [v.slug for v in game_variants],
        'limits': [
            {
                'id': limits_by_slug[v.slug].id if v.slug in limits_by_slug else None,
                'variant': v.slug,
                'label': v.label,
                'max_offers': limits_by_slug[v.slug].max_offers if v.slug in limits_by_slug else None,
                'stock_reserve': limits_by_slug[v.slug].stock_reserve if v.slug in limits_by_slug else None,
            }
            for v in game_variants
        ],
        'active_counts': counts,
    })


@login_required
@role_required('admin', 'user')
@require_POST
def save_variant_limits(request):
    """Bulk upsert platform variant limits for a store×game pair.

    Body: { store_id, game_id, limits: [{ variant, max_offers, stock_reserve }] }
    Variants not included in the list are deleted.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    store_id = body.get('store_id')
    game_id = body.get('game_id')
    limits_data = body.get('limits', [])

    if not store_id or not game_id:
        return JsonResponse({'error': 'store_id and game_id are required'}, status=400)

    try:
        store = IntegrationAccount.objects.get(id=store_id)
        game = Game.objects.get(id=game_id)
    except (IntegrationAccount.DoesNotExist, Game.DoesNotExist):
        return JsonResponse({'error': 'Store or game not found'}, status=404)

    game_variants = {
        v.slug: v
        for v in GameVariant.objects.filter(game=game, type='platform')
    }
    if not game_variants:
        return JsonResponse({'error': 'This game does not support variants'}, status=400)

    # Validate incoming limits
    seen: set[str] = set()
    validated: list[tuple[str, int, int]] = []
    for entry in limits_data:
        sp = (entry.get('variant') or '').strip()
        if not sp or sp not in game_variants:
            return JsonResponse({'error': f'Invalid variant: {sp}'}, status=400)
        if sp in seen:
            return JsonResponse({'error': f'Duplicate variant: {sp}'}, status=400)
        seen.add(sp)

        try:
            max_offers = int(entry.get('max_offers', 0))
            stock_reserve = int(entry.get('stock_reserve', 0))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'max_offers and stock_reserve must be integers'}, status=400)

        if max_offers < 0 or stock_reserve < 0:
            return JsonResponse({'error': 'max_offers and stock_reserve must be >= 0'}, status=400)
        if stock_reserve > max_offers:
            return JsonResponse(
                {'error': f'{sp}: stock_reserve ({stock_reserve}) cannot exceed max_offers ({max_offers})'},
                status=400,
            )

        validated.append((sp, max_offers, stock_reserve))

    # Delete limits for variants not in the request
    GameVariantLimit.objects.filter(
        store=store, variant__game=game, variant__type='platform',
    ).exclude(variant__slug__in=seen).delete()

    # Upsert each limit
    for sp, max_offers, stock_reserve in validated:
        GameVariantLimit.objects.update_or_create(
            store=store, variant=game_variants[sp],
            defaults={'max_offers': max_offers, 'stock_reserve': stock_reserve},
        )

    return JsonResponse({'ok': True, 'saved': len(validated)})


@login_required
@require_GET
def dropship_stats(request):
    """General dropship statistics."""
    active_items = DropshipProduct.objects.filter(
        status=DropshipProductStatus.LISTED,
    ).count()

    configs_count = DropshippingJobConfig.objects.filter(enabled=True).count()

    recent_logs = PostingLog.objects.filter(
        task_name__in=['dropship_poster', 'dropship_cleaner'],
    ).order_by('-created_at')[:20]

    return JsonResponse({
        'active_items': active_items,
        'active_configs': configs_count,
        'recent_logs': [
            {
                'id': log.id,
                'task_name': log.task_name,
                'level': log.level,
                'message': log.message,
                'created_at': log.created_at.isoformat(),
            }
            for log in recent_logs
        ],
    })
