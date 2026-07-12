"""Dropship API endpoints — config CRUD, target URL management, scheduler control, stats."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET, require_http_methods

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
from apps.posting.services.variant_slug import variant_value_contains_slug

logger = logging.getLogger(__name__)


def _resolve_variant_counts(
    raw: dict[str, int],
    variants: list[GameVariant],
) -> dict[str, int]:
    """Convert composite variant counts to component-slug counts.

    DB stores composite values like 'eu-pc', 'na-psn'. This maps them back
    to the component slug used for capacity management (e.g. 'pc', 'psn').
    Single-dimension games (variant == slug directly) also work correctly.
    """
    known_slugs = {v.slug.lower() for v in variants}
    result: dict[str, int] = {v.slug: 0 for v in variants}
    for composite, count in raw.items():
        for v in variants:
            if variant_value_contains_slug(composite, v.slug, known_slugs=known_slugs):
                result[v.slug] += count
    return result


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
    3. If the game has region variants (and no platform variants), at least one
       GameVariantLimit must be configured (otherwise dropship capacity = 0 by default).
    """
    has_urls = DropshipTargetURL.objects.filter(config=config, enabled=True).exists()
    if not has_urls:
        return 'Cannot enable: add at least one enabled target URL first'

    has_platform = GameVariant.objects.filter(game=config.game, type='platform').exists()
    has_region = GameVariant.objects.filter(game=config.game, type='region').exists()

    if has_platform:
        has_limits = GameVariantLimit.objects.filter(
            store=config.store, variant__game=config.game, variant__type='platform',
        ).exists()
        if not has_limits:
            return (
                'Cannot enable: configure variant limits first '
                f'(game "{config.game.name}" requires variant selection)'
            )
    elif has_region:
        has_limits = GameVariantLimit.objects.filter(
            store=config.store, variant__game=config.game, variant__type='region',
        ).exists()
        if not has_limits:
            return (
                'Cannot enable: configure region limits first '
                f'(game "{config.game.name}" requires at least one region to be configured)'
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

    # Pre-fetch all variants + limits + active counts for all (store, game) pairs
    # to avoid N+1 queries inside the config loop.
    _all_game_ids = {c.game_id for c in configs}
    _all_variants = list(
        GameVariant.objects
        .filter(game_id__in=_all_game_ids)
        .order_by('game_id', 'type', 'sort_order')
    )
    variants_by_game: dict[int, list[GameVariant]] = {}
    for v in _all_variants:
        variants_by_game.setdefault(v.game_id, []).append(v)

    variant_limits_map: dict[tuple[int, int], list[GameVariantLimit]] = {}
    active_counts_map: dict[tuple[int, int], dict[str, int]] = {}

    for c in configs:
        key = (c.store_id, c.game_id)
        if key not in variant_limits_map and c.game_id in variants_by_game:
            variant_limits_map[key] = list(
                GameVariantLimit.objects
                .filter(store_id=c.store_id, variant__game_id=c.game_id)
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

        # When a game has platform variants, only expose platform for capacity management.
        # Region is auto-determined from account data — no user-configured limits needed.
        if any(v.type == 'platform' for v in game_variants):
            game_variants = [v for v in game_variants if v.type == 'platform']

        key = (config.store_id, config.game_id)
        limits = variant_limits_map.get(key, [])
        counts = _resolve_variant_counts(active_counts_map.get(key, {}), game_variants)
        limits_by_slug = {lim.variant.slug: lim for lim in limits}

        return {
            'has_variants': True,
            'variant_limits': [
                {
                    'variant': v.slug,
                    'label': v.label,
                    'type': v.type,
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
            'source_account': {'id': c.source_account.id, 'name': c.source_account.name, 'provider': c.source_account.provider},
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
                    'seller_username': u.seller_username or '',
                    'last_fetched_at': u.last_fetched_at.isoformat() if u.last_fetched_at else None,
                    'last_error': u.last_error,
                    'processing_state': u.processing_state,
                    'cycle_found': u.cycle_found,
                    'cycle_new': u.cycle_new,
                    'cycle_posted': u.cycle_posted,
                }
                for u in c.target_urls.all()
            ],
            'active_total': sum(active_counts_map.get((c.store_id, c.game_id), {}).values()),
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
        seller_username=(body.get('seller_username') or '').strip(),
    )

    return JsonResponse({'id': target_url.id}, status=201)


@require_http_methods(['POST'])
@login_required
def bulk_create_dropship_urls(request, config_id):
    """Create one DropshipTargetURL per seller from a list of seller usernames."""
    try:
        config = DropshippingJobConfig.objects.get(id=config_id)
    except DropshippingJobConfig.DoesNotExist:
        return JsonResponse({'error': 'Config not found'}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    sellers = data.get('sellers', [])
    if not sellers or not isinstance(sellers, list):
        return JsonResponse({'error': 'sellers list is required'}, status=400)
    url_base = data.get('url', '')
    multiplier_low = data.get('multiplier_low', 2.0)
    multiplier_mid = data.get('multiplier_mid', 1.8)
    multiplier_high = data.get('multiplier_high', 1.5)
    min_price = data.get('min_price', 0)
    forced_ending = data.get('forced_ending', 0.99)
    created = 0
    skipped = 0
    for seller in sellers:
        seller = seller.strip()
        if not seller:
            continue
        # Skip if this seller already exists for this config
        if DropshipTargetURL.objects.filter(config=config, seller_username=seller).exists():
            skipped += 1
            continue
        err = _validate_numeric_fields({
            'multiplier_low': multiplier_low,
            'multiplier_mid': multiplier_mid,
            'multiplier_high': multiplier_high,
            'min_price': min_price,
        }, _URL_LIMITS)
        if err:
            return JsonResponse({'error': err}, status=400)
        DropshipTargetURL.objects.create(
            config=config,
            url=url_base,
            multiplier_low=multiplier_low,
            multiplier_mid=multiplier_mid,
            multiplier_high=multiplier_high,
            min_price=min_price,
            forced_ending=forced_ending if forced_ending is not None else None,
            seller_username=seller,
            enabled=True,
        )
        created += 1
    return JsonResponse({'ok': True, 'created': created, 'skipped': skipped}, status=201)


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
                  'multiplier_high', 'min_price', 'forced_ending', 'seller_username'):
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
        GameVariant.objects.filter(game=game).order_by('type', 'sort_order')
    )
    # When a game has platform variants, only expose platform for capacity management.
    # Region is auto-determined from account data — no user-configured limits needed.
    if any(v.type == 'platform' for v in game_variants):
        game_variants = [v for v in game_variants if v.type == 'platform']
    limits = list(
        GameVariantLimit.objects
        .filter(store=store, variant__game=game)
        .select_related('variant')
    )
    counts: dict[str, int] = {}
    if game_variants:
        raw_counts = dict(
            Listing.objects
            .filter(integration_account=store, game=game, status=ListingStatus.LISTED)
            .values('variant')
            .annotate(count=Count('id'))
            .values_list('variant', 'count')
        )
        counts = _resolve_variant_counts(raw_counts, game_variants)

    limits_by_slug = {lim.variant.slug: lim for lim in limits}

    return JsonResponse({
        'has_variants': bool(game_variants),
        'available_variants': [v.slug for v in game_variants],
        'limits': [
            {
                'id': limits_by_slug[v.slug].id if v.slug in limits_by_slug else None,
                'variant': v.slug,
                'label': v.label,
                'type': v.type,
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
        for v in GameVariant.objects.filter(game=game)
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
        store=store, variant__game=game,
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


@login_required
@role_required('admin', 'user')
def seller_check(request):
    """GET /api/dropship/seller-check/?username=OdbougShop&config_id=2
    Checks if a seller exists in current Eldorado listings and returns their profile.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    username = (request.GET.get('username') or '').strip()
    config_id = request.GET.get('config_id')

    if not username:
        return JsonResponse({'error': 'username is required'}, status=400)

    try:
        from apps.posting.models import DropshippingJobConfig
        from apps.posting.services.dropship.sources.eldorado import EldoradoSourceProvider
        from apps.integrations.proxy_pool import build_proxy_pool

        # Get the source account credential from the config if provided
        credential = None
        if config_id:
            try:
                config = DropshippingJobConfig.objects.select_related('source_account__credential').get(id=config_id)
                credential = config.source_account.credential
            except DropshippingJobConfig.DoesNotExist:
                pass

        if credential is None:
            # Fall back to any active Eldorado account
            from apps.integrations.models import IntegrationAccount
            acc = IntegrationAccount.objects.filter(provider='eldorado', is_active=True).first()
            if acc:
                credential = acc.credential

        if credential is None:
            return JsonResponse({'found': False, 'error': 'No Eldorado credential available'})

        provider = EldoradoSourceProvider(credential=credential)
        session = provider._get_session()

        # --- Fast path: profile page scrape to get UUID (O(1) HTTP request) ---
        # The seller's avatar URL contains their UUID:
        #   https://assetsdelivery.eldorado.gg/v7/_profiles-v2_/{UUID}_Avatar_...
        import re as _re
        found_user = None
        seller_uuid = None
        try:
            profile_resp = session.get(
                f'https://www.eldorado.gg/users/{username}/shop',
                timeout=10,
            )
            if profile_resp.ok:
                uuid_pat = _re.compile(
                    r'_profiles-v2_/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_Avatar_',
                    _re.IGNORECASE,
                )
                m = uuid_pat.search(profile_resp.text)
                if m:
                    seller_uuid = m.group(1)
                    # Fetch one item using userId to get full user object
                    item_resp = session.get(
                        'https://www.eldorado.gg/api/v1/item-management/offers',
                        params={'userId': seller_uuid, 'pageSize': 1},
                        timeout=10,
                    )
                    if item_resp.ok:
                        results = item_resp.json().get('results') or []
                        if results:
                            found_user = results[0].get('user') or {}
                    if not found_user:
                        # Build minimal user object from what we know
                        found_user = {'id': seller_uuid, 'username': username}
        except Exception as _exc:
            import logging
            logging.getLogger(__name__).debug("Profile page scrape failed for '%s': %s", username, _exc)

        # --- Fallback: scan first 3 pages of listings ---
        if not found_user:
            for page in range(1, 4):
                resp = session.get(
                    'https://www.eldorado.gg/api/v1/item-management/offers',
                    params={'gameId': 259, 'category': 'CustomItem', 'pageSize': 20, 'page': page},
                    timeout=10,
                )
                if not resp.ok:
                    break
                data = resp.json()
                results = data.get('results') or []
                for entry in results:
                    user = entry.get('user') or {}
                    if (user.get('username') or '').lower() == username.lower():
                        found_user = user
                        seller_uuid = user.get('id') or ''
                        break
                if found_user:
                    break
                if not results:
                    break

        if found_user:
            seller_id = found_user.get('id') or seller_uuid or ''
            # Auto-save UUID to matching DropshipTargetURL records
            if seller_id:
                try:
                    from apps.posting.models import DropshipTargetURL
                    qs = DropshipTargetURL.objects.filter(seller_username__iexact=username)
                    if config_id:
                        qs = qs.filter(config_id=config_id)
                    qs.update(seller_uuid=seller_id)
                except Exception:
                    pass
            return JsonResponse({
                'found': True,
                'uuid': seller_id,
                'username': found_user.get('username') or username,
                'isVerifiedSeller': found_user.get('isVerifiedSeller') or False,
                'rating': found_user.get('rating') or 0,
                'description': (found_user.get('description') or '')[:200],
                'createdDate': found_user.get('createdDate') or '',
            })
        else:
            return JsonResponse({
                'found': False,
                'username': username,
                'note': 'Seller profile not found on Eldorado. Check the username spelling.',
            })
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("seller_check error: %s", e)
        return JsonResponse({'found': False, 'error': str(e)})
