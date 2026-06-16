"""Offer Pool (Auto Restock) API endpoints."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET, require_http_methods

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
from apps.orders.enums import OrderStatus
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
)

logger = logging.getLogger(__name__)


# ── Pool CRUD ─────────────────────────────────────────────────────


@login_required
@require_GET
def list_pools(request):
    """List all offer pools with summary stats."""
    pools = (
        OfferPool.objects
        .select_related('listing', 'game', 'store')
        .order_by('-created_at')
    )

    # Optional filters
    game_id = request.GET.get('game')
    if game_id:
        pools = pools.filter(game_id=game_id)

    status = request.GET.get('status')
    if status in OfferPoolStatus.values:
        pools = pools.filter(status=status)

    data = []
    for pool in pools:
        data.append(_pool_to_dict(pool))

    return JsonResponse({'pools': data})


@login_required
@require_POST
def create_pool(request):
    """Create a new offer pool.

    POST body (JSON):
        listing_id: int          — existing Listing to restock
        threshold: int           — trigger when below (default 10)
        target_count: int        — fill up to (default 50)
        max_concurrent: int      — PA only: simultaneous offers (default 1)
        credentials: list[dict]  — optional initial credentials to add
        game_id: int             — game for the pool

    After creation, if credentials are provided and pool is below threshold,
    an immediate replenish is triggered.
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    listing_id = body.get('listing_id')
    if not listing_id:
        return JsonResponse({'error': 'listing_id is required'}, status=400)

    try:
        listing = Listing.objects.select_related('integration_account', 'game').get(id=listing_id)
    except Listing.DoesNotExist:
        return JsonResponse({'error': 'Listing not found'}, status=404)

    # Check if pool already exists for this listing
    if OfferPool.objects.filter(listing=listing).exists():
        return JsonResponse({'error': 'Pool already exists for this listing'}, status=409)

    store = listing.integration_account
    if not store:
        return JsonResponse({'error': 'Listing has no associated store'}, status=400)

    game_id = body.get('game_id') or (listing.game_id if listing.game else None)
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    # Determine strategy based on marketplace
    marketplace = store.provider
    if marketplace == 'playerauctions':
        strategy = OfferPool.Strategy.CLONE
    elif marketplace in ('eldorado', 'gameboost'):
        strategy = OfferPool.Strategy.APPEND
    else:
        return JsonResponse({'error': f'Unsupported marketplace: {marketplace}'}, status=400)

    pool = OfferPool.objects.create(
        listing=listing,
        game=game,
        store=store,
        strategy=strategy,
        status=OfferPoolStatus.DEPLETED,  # Start depleted, activate when items added
        threshold=body.get('threshold', 10),
        target_count=body.get('target_count', 50),
        max_concurrent=body.get('max_concurrent', 1),
    )

    # Add initial credentials if provided
    credentials = body.get('credentials', [])
    create_result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}
    if credentials:
        _add_credentials_to_pool(pool, credentials, game, listing=listing,
                                 force=True, result=create_result)

    # Activate pool if items were added
    if create_result['added'] > 0 and pool.status == OfferPoolStatus.DEPLETED:
        pool.status = OfferPoolStatus.ACTIVE
        pool.save(update_fields=['status', 'updated_at'])

    pool.refresh_from_db()
    return JsonResponse({
        'pool': _pool_to_dict(pool),
        **create_result,
    }, status=201)


@login_required
@require_GET
def pool_detail(request, pool_id):
    """Get pool detail with all items."""
    try:
        pool = (
            OfferPool.objects
            .select_related('listing', 'game', 'store')
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    items = list(
        pool.items
        .select_related('owned_product')
        .order_by('order', 'created_at')
    )

    active_offers = list(
        pool.active_offers
        .select_related('listing', 'pool_item')
        .order_by('-created_at')
    )

    return JsonResponse({
        'pool': _pool_to_dict(pool),
        'items': [_item_to_dict(item) for item in items],
        'active_offers': [_active_offer_to_dict(ao) for ao in active_offers],
    })


@login_required
@require_http_methods(['PATCH'])
def update_pool(request, pool_id):
    """Update pool settings (threshold, target, enabled/paused, max_concurrent)."""
    try:
        pool = OfferPool.objects.get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    update_fields = ['updated_at']

    if 'threshold' in body:
        pool.threshold = int(body['threshold'])
        update_fields.append('threshold')

    if 'target_count' in body:
        pool.target_count = int(body['target_count'])
        update_fields.append('target_count')

    if 'max_concurrent' in body:
        pool.max_concurrent = int(body['max_concurrent'])
        update_fields.append('max_concurrent')

    if 'status' in body:
        new_status = body['status']
        if new_status in OfferPoolStatus.values:
            # Don't allow activating a pool with no pending items
            if new_status == OfferPoolStatus.ACTIVE:
                has_pending = pool.items.filter(status=OfferPoolItemStatus.PENDING).exists()
                if not has_pending:
                    return JsonResponse({'error': 'Cannot activate pool with no pending items'}, status=400)
            pool.status = new_status
            update_fields.append('status')

    pool.save(update_fields=update_fields)
    return JsonResponse({'pool': _pool_to_dict(pool)})


@login_required
@require_POST
def delete_pool(request, pool_id):
    """Delete a pool and all its items."""
    try:
        pool = OfferPool.objects.get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    pool.delete()
    return JsonResponse({'ok': True})


# ── Pool Item Management ─────────────────────────────────────────


@login_required
@require_POST
def add_pool_items(request, pool_id):
    """Add credentials to a pool with validation.

    POST body (JSON):
        credentials: list[dict]  — [{login, password, email?, ...}]
        owned_product_ids: list[int] — existing OwnedProduct IDs to add
        force: bool              — skip warnings (sold accounts) and add anyway

    Response:
        added: int
        total_pending: int
        skipped: [{login, reason, detail?}]   — blocked, not added
        warnings: [{login, reason, detail?}]  — added despite warning (or needs confirm)
        needs_confirmation: [login, ...]       — re-submit with force=true to add these
    """
    try:
        pool = OfferPool.objects.select_related('game', 'listing', 'store').get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    force = bool(body.get('force', False))
    result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}

    # Mode 1: raw credentials → create OwnedProducts + add to pool
    credentials = body.get('credentials', [])
    if credentials:
        _add_credentials_to_pool(pool, credentials, pool.game, listing=pool.listing,
                                 force=force, result=result)

    # Mode 2: existing OwnedProduct IDs
    owned_product_ids = body.get('owned_product_ids', [])
    if owned_product_ids:
        products = OwnedProduct.objects.filter(id__in=owned_product_ids)
        max_order = pool.items.count()
        for i, product in enumerate(products):
            check = _validate_pool_candidate(product, pool)
            if check['block']:
                result['skipped'].append({
                    'login': product.login,
                    'reason': check['block_reason'],
                    'detail': check['block_detail'],
                })
                continue
            if not _process_warnings(check, product.login, force, result):
                continue

            _, created = OfferPoolItem.objects.get_or_create(
                pool=pool,
                owned_product=product,
                defaults={'order': max_order + i},
            )
            if created:
                result['added'] += 1

    # Re-activate pool if it was depleted and we added items
    if result['added'] > 0 and pool.status == OfferPoolStatus.DEPLETED:
        pool.status = OfferPoolStatus.ACTIVE
        pool.save(update_fields=['status', 'updated_at'])

    pool.refresh_from_db()
    result['total_pending'] = pool.pending_count
    return JsonResponse(result)


@login_required
@require_POST
def remove_pool_item(request, pool_id, item_id):
    """Remove a single item from pool (only if PENDING)."""
    try:
        item = OfferPoolItem.objects.get(id=item_id, pool_id=pool_id)
    except OfferPoolItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)

    if item.status != OfferPoolItemStatus.PENDING:
        return JsonResponse({'error': f'Cannot remove item with status {item.status}'}, status=400)

    item.delete()
    return JsonResponse({'ok': True})


# ── Pool Actions ─────────────────────────────────────────────────


@login_required
@require_POST
def trigger_replenish(request, pool_id):
    """Manually trigger a replenish check for a pool."""
    from apps.posting.services.pool.checker import _check_and_replenish

    try:
        pool = (
            OfferPool.objects
            .select_related('listing', 'store', 'store__credential', 'game')
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    if pool.status != OfferPoolStatus.ACTIVE:
        return JsonResponse({'error': f'Pool is {pool.status}, not active'}, status=400)

    try:
        pushed = _check_and_replenish(pool, force=True)
    except Exception as exc:
        logger.exception('pool API: manual replenish failed for pool %d', pool_id)
        return JsonResponse({'error': str(exc)[:500]}, status=500)

    pool.refresh_from_db()
    return JsonResponse({
        'pushed': pushed,
        'pool': _pool_to_dict(pool),
    })


# ── Pool Offer Edit ──────────────────────────────────────────────


@login_required
@require_POST
def edit_pool_offers(request, pool_id):
    """Edit title/description/price of all offers in a pool."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    try:
        pool = (
            OfferPool.objects
            .select_related('listing', 'store', 'store__credential', 'game')
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    changes = {}
    if 'title' in body and body['title']:
        changes['title'] = str(body['title']).strip()
    if 'description' in body and body['description']:
        changes['description'] = str(body['description']).strip()
    if 'price' in body and body['price'] is not None:
        try:
            changes['price'] = round(float(body['price']), 2)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid price'}, status=400)

    if not changes:
        return JsonResponse({'error': 'No changes provided'}, status=400)

    from apps.posting.services.offer_editor import edit_pool_offers as _edit_pool_offers

    try:
        result = _edit_pool_offers(pool, changes)
    except Exception as exc:
        logger.exception('pool API: edit_pool_offers failed for pool %d', pool_id)
        return JsonResponse({'error': str(exc)[:500]}, status=500)

    status_code = 200 if result.failed == 0 else 207
    return JsonResponse({
        'ok': result.failed == 0,
        'total': result.total,
        'succeeded': result.succeeded,
        'failed': result.failed,
        'errors': result.errors,
    }, status=status_code)


# ── Sweep Settings ───────────────────────────────────────────────


@login_required
@require_GET
def sweep_settings(request):
    """Get current pool sweep settings."""
    from apps.sync.services.shared.feature_flags import SyncFlag, get_sync_setting, is_sync_feature_enabled

    return JsonResponse({
        'enabled': is_sync_feature_enabled(SyncFlag.POOL_SWEEP),
        'interval_minutes': get_sync_setting(SyncFlag.POOL_SWEEP, 'interval_minutes', default=30),
    })


@login_required
@require_POST
def update_sweep_settings(request):
    """Update pool sweep interval and enabled state."""
    from apps.sync.models import SyncFeatureFlag
    from apps.sync.services.shared.feature_flags import SyncFlag

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    flag, _ = SyncFeatureFlag.objects.get_or_create(
        key=SyncFlag.POOL_SWEEP,
        defaults={'description': 'Offer pool auto-restock sweep'},
    )

    if 'enabled' in body:
        flag.is_enabled = bool(body['enabled'])

    if 'interval_minutes' in body:
        interval = int(body['interval_minutes'])
        if interval < 1:
            return JsonResponse({'error': 'interval_minutes must be >= 1'}, status=400)
        value = flag.value or {}
        value['interval_minutes'] = interval
        flag.value = value

    flag.save()

    return JsonResponse({
        'enabled': flag.is_enabled,
        'interval_minutes': (flag.value or {}).get('interval_minutes', 30),
    })


# ── Available Accounts for Pool ──────────────────────────────────


@login_required
@require_GET
def available_accounts(request):
    """List OwnedProducts available for pool assignment.

    Filters: game_id (required), q (search login), exclude_pool_id.
    """
    game_id = request.GET.get('game_id')
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    qs = OwnedProduct.objects.filter(
        game_id=game_id,
    ).order_by('-created_at')

    # Exclude items already in a specific pool
    exclude_pool = request.GET.get('exclude_pool_id')
    if exclude_pool:
        existing_ids = OfferPoolItem.objects.filter(
            pool_id=exclude_pool,
        ).values_list('owned_product_id', flat=True)
        qs = qs.exclude(id__in=existing_ids)

    # Search
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(login__icontains=q)

    # Pagination (simple offset/limit)
    limit = min(int(request.GET.get('limit', 50)), 200)
    offset = int(request.GET.get('offset', 0))
    total = qs.count()
    products = qs[offset:offset + limit]

    data = []
    for p in products:
        data.append({
            'id': p.id,
            'login': p.login,
            'email': p.email or '',
            'status': p.status,
            'price': str(p.price) if p.price else None,
            'created_at': p.created_at.isoformat(),
        })

    return JsonResponse({'accounts': data, 'total': total})


# ── Available Listings for Pool ──────────────────────────────────


@login_required
@require_GET
def available_listings(request):
    """List active listings that can have a pool created.

    Filters: game_id, store_id, q (search title/offer_id).
    Returns only listings without an existing pool.
    """
    qs = (
        Listing.objects
        .filter(status='listed')
        .select_related('integration_account', 'game')
        .exclude(offer_pools__isnull=False)
        .order_by('-created_at')
    )

    game_id = request.GET.get('game_id')
    if game_id:
        qs = qs.filter(game_id=game_id)

    store_id = request.GET.get('store_id')
    if store_id:
        qs = qs.filter(integration_account_id=store_id)

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=q) | Q(store_listing_id__icontains=q))

    limit = min(int(request.GET.get('limit', 50)), 200)
    offset = int(request.GET.get('offset', 0))
    total = qs.count()
    listings = qs[offset:offset + limit]

    data = []
    for lst in listings:
        data.append({
            'id': lst.id,
            'title': lst.title or lst.store_listing_id,
            'store_listing_id': lst.store_listing_id,
            'store': lst.integration_account.name if lst.integration_account else '',
            'marketplace': lst.integration_account.provider if lst.integration_account else '',
            'game': lst.game.name if lst.game else '',
            'game_id': lst.game_id,
            'price': str(lst.price),
            'variant': lst.variant,
            'created_at': lst.created_at.isoformat(),
        })

    return JsonResponse({'listings': data, 'total': total})


# ── Serializers ──────────────────────────────────────────────────


def _pool_to_dict(pool: OfferPool) -> dict:
    pending = pool.items.filter(status=OfferPoolItemStatus.PENDING).count()
    pushed = pool.items.filter(status=OfferPoolItemStatus.PUSHED).count()
    failed = pool.items.filter(status=OfferPoolItemStatus.FAILED).count()
    consumed = pool.items.filter(status=OfferPoolItemStatus.CONSUMED).count()

    return {
        'id': pool.id,
        'listing_id': pool.listing_id,
        'listing_title': pool.listing.title or pool.listing.store_listing_id,
        'offer_id': pool.listing.store_listing_id,
        'game': pool.game.name if pool.game else '',
        'game_id': pool.game_id,
        'store': pool.store.name if pool.store else '',
        'store_id': pool.store_id,
        'marketplace': pool.store.provider if pool.store else '',
        'strategy': pool.strategy,
        'status': pool.status,
        'threshold': pool.threshold,
        'target_count': pool.target_count,
        'max_concurrent': pool.max_concurrent,
        'current_remote_count': pool.current_remote_count,
        'last_checked_at': pool.last_checked_at.isoformat() if pool.last_checked_at else None,
        'last_replenished_at': pool.last_replenished_at.isoformat() if pool.last_replenished_at else None,
        'items_pending': pending,
        'items_pushed': pushed,
        'items_failed': failed,
        'items_consumed': consumed,
        'items_total': pending + pushed + failed + consumed,
        'created_at': pool.created_at.isoformat(),
    }


def _item_to_dict(item: OfferPoolItem) -> dict:
    return {
        'id': item.id,
        'owned_product_id': item.owned_product_id,
        'login': item.owned_product.login if item.owned_product else '',
        'email': item.owned_product.email if item.owned_product else '',
        'status': item.status,
        'order': item.order,
        'pushed_at': item.pushed_at.isoformat() if item.pushed_at else None,
        'target_offer_id': item.target_offer_id,
        'error_message': item.error_message,
    }


def _active_offer_to_dict(ao: OfferPoolActiveOffer) -> dict:
    return {
        'id': ao.id,
        'store_listing_id': ao.store_listing_id,
        'status': ao.status,
        'pool_item_login': ao.pool_item.owned_product.login if ao.pool_item and ao.pool_item.owned_product else '',
        'created_at': ao.created_at.isoformat(),
    }


# ── Internal helpers ─────────────────────────────────────────────


# Legacy platform-specific credential key mappings (GTA fallback)
_PLATFORM_CREDENTIAL_MAP: dict[str, tuple[str, str, tuple[str, ...]]] = {
    'PlayStation 4':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'PlayStation 5':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'Xbox One':        ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'Xbox Series X/S': ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'PC - Legacy':     ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
    'PC - Enhanced':   ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
}


def _validate_pool_candidate(
    owned: OwnedProduct,
    pool: OfferPool,
) -> dict:
    """Check if an OwnedProduct can be added to a pool.

    Returns:
        {block: bool, block_reason, block_detail,
         warnings: [{reason, detail, needs_confirm}]}
    """
    result: dict = {
        'block': False, 'block_reason': '', 'block_detail': '',
        'warnings': [],
    }

    # 1. Already in this pool
    if OfferPoolItem.objects.filter(pool=pool, owned_product=owned).exists():
        result['block'] = True
        result['block_reason'] = 'already_in_pool'
        result['block_detail'] = f'Already in Pool #{pool.pk}'
        return result

    # 2. Already linked to this pool's listing (ListingOwnedProduct)
    if pool.listing_id and ListingOwnedProduct.objects.filter(
        listing_id=pool.listing_id,
        owned_product=owned,
    ).exists():
        result['block'] = True
        result['block_reason'] = 'linked_to_listing'
        result['block_detail'] = 'Already linked to this offer'
        return result

    # 3. In another pool on the SAME marketplace → block
    pool_marketplace = pool.store.provider if pool.store else ''
    other_pool_item = (
        OfferPoolItem.objects
        .filter(
            owned_product=owned,
            status__in=(OfferPoolItemStatus.PENDING, OfferPoolItemStatus.PUSHED),
        )
        .exclude(pool=pool)
        .select_related('pool__store')
        .first()
    )
    if other_pool_item:
        other_mp = other_pool_item.pool.store.provider if other_pool_item.pool.store else ''
        other_pool = other_pool_item.pool
        if other_mp == pool_marketplace:
            result['block'] = True
            result['block_reason'] = 'in_pool_same_marketplace'
            result['block_detail'] = (
                f'Already in Pool #{other_pool.pk} '
                f'({other_pool.store.name if other_pool.store else other_mp})'
            )
            return result
        # Different marketplace → info warning (no confirmation needed)
        result['warnings'].append({
            'reason': 'in_pool_other_marketplace',
            'detail': (
                f'Also in Pool #{other_pool.pk} '
                f'({other_pool.store.name if other_pool.store else other_mp})'
            ),
            'needs_confirm': False,
        })

    # 4. Sold (has active sold order, not cancelled/refunded) → needs confirmation
    _SOLD_STATUSES = (OrderStatus.PENDING, OrderStatus.DELIVERED, OrderStatus.COMPLETED)
    sold_order = owned.orders.filter(status__in=_SOLD_STATUSES).first()
    if sold_order:
        sold_date = sold_order.created_at.strftime('%Y-%m-%d') if sold_order.created_at else '?'
        result['warnings'].append({
            'reason': 'sold',
            'detail': f'Sold on {sold_date}, not refunded/cancelled',
            'needs_confirm': True,
        })

    return result


def _process_warnings(
    check: dict,
    login: str,
    force: bool,
    result: dict,
) -> bool:
    """Process validation warnings. Returns True if item should be added, False to skip.

    Adds entries to result['warnings'] and result['needs_confirmation'] as needed.
    """
    warnings = check.get('warnings', [])
    if not warnings:
        return True

    needs_confirm = any(w['needs_confirm'] for w in warnings)

    for w in warnings:
        result['warnings'].append({
            'login': login,
            'reason': w['reason'],
            'detail': w['detail'],
        })

    if needs_confirm and not force:
        result['needs_confirmation'].append(login)
        return False

    return True


def _get_or_create_owned_product(
    game: Game,
    login: str,
    password: str,
    *,
    ref_price=None,
    extra_fields: dict | None = None,
    raw_data: dict | None = None,
) -> tuple[OwnedProduct, bool]:
    """Get or create an OwnedProduct. On update, only touch credential fields — never status.

    Returns (owned_product, created).
    """
    try:
        owned = OwnedProduct.objects.get(category=game.category, login=login)
        # Existing product: update only credential fields, PRESERVE status/price
        owned.password = password
        owned.password_hash = hashlib.sha256(password.encode()).hexdigest()
        owned.game = game
        update_fields = ['password', 'password_hash', 'game', 'updated_at']

        if extra_fields:
            for field, value in extra_fields.items():
                setattr(owned, field, value)
                update_fields.append(field)

        if raw_data is not None:
            owned.raw_data = raw_data
            update_fields.append('raw_data')

        owned.save(update_fields=update_fields)
        return owned, False

    except OwnedProduct.DoesNotExist:
        create_kwargs = {
            'category': game.category,
            'login': login,
            'password': password,
            'password_hash': hashlib.sha256(password.encode()).hexdigest(),
            'game': game,
            'status': 'draft',
            'price': ref_price,
            'raw_data': raw_data or {},
        }
        if extra_fields:
            create_kwargs.update(extra_fields)
        owned = OwnedProduct.objects.create(**create_kwargs)
        return owned, True


def _add_credentials_to_pool(
    pool: OfferPool,
    credentials: list[dict],
    game: Game,
    listing: Listing | None = None,
    *,
    force: bool = False,
    result: dict | None = None,
) -> int:
    """Create OwnedProducts from raw credentials and add as OfferPoolItems.

    Spec-driven: uses CredentialSpec field roles to map incoming keys to
    OwnedProduct fixed columns. Falls back to legacy _PLATFORM_CREDENTIAL_MAP
    if no spec is resolved.

    Args:
        force: If True, skip warnings (sold accounts) and add anyway.
        result: Mutable dict to collect skipped/warnings/needs_confirmation.
    """
    from apps.posting.services.pool.spec_resolver import (
        build_field_role_map,
        build_reverse_role_map,
        resolve_spec,
    )
    from apps.posting.services.pool.presets import ROLE_TO_OWNED_PRODUCT_FIELD

    if result is None:
        result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}

    max_order = pool.items.count()
    platform = (listing.variant or '') if listing else ''

    # Get reference price from listing's existing owned products
    ref_price = None
    if listing:
        ref_lop = (
            ListingOwnedProduct.objects
            .filter(listing=listing, owned_product__price__isnull=False)
            .select_related('owned_product')
            .first()
        )
        if ref_lop:
            ref_price = ref_lop.owned_product.price

    # Try spec-driven ingestion (DB spec or code-level preset)
    spec = resolve_spec(pool)

    # If no DB spec, try code-level preset as structured fallback
    spec_fields = None
    spec_id = None
    if spec:
        spec_fields = spec.fields
        spec_id = spec.id
    else:
        from apps.posting.services.pool.spec_resolver import resolve_game_variant
        from apps.posting.services.pool.presets import get_preset
        game_slug = game.slug if game else ''
        variant_obj = resolve_game_variant(game, platform) if platform and game else None
        variant_slug = variant_obj.slug if variant_obj else None
        preset = get_preset(game_slug, variant_slug)
        if preset:
            spec_fields = preset[1]  # fields list

    if spec_fields:
        role_map = build_field_role_map(spec_fields)
        reverse_map = build_reverse_role_map(spec_fields)
        login_key = role_map.get('login', 'login')
        password_key = role_map.get('password', 'password')

        for i, cred in enumerate(credentials):
            login = str(cred.get(login_key, '')).strip().lower()
            password = str(cred.get(password_key, '')).strip()

            if not login or not password:
                continue

            raw_data = {
                'source': 'manual',
                'main_platform': platform,
                'credential_spec_id': spec_id,
                'credential_values': cred,
                'loginData': {'login': login, 'password': password},
                'item_id': f'manual-{uuid.uuid4().hex[:12]}',
            }

            extra_fields: dict = {}
            for field_key, role in reverse_map.items():
                value = str(cred.get(field_key, '')).strip()
                owned_field = ROLE_TO_OWNED_PRODUCT_FIELD.get(role)
                if owned_field:
                    extra_fields[owned_field] = value
                elif role == 'extra' and value:
                    raw_data[field_key] = value

            owned, _ = _get_or_create_owned_product(
                game, login, password,
                ref_price=ref_price,
                extra_fields=extra_fields,
                raw_data=raw_data,
            )

            # Validate before adding to pool
            check = _validate_pool_candidate(owned, pool)
            if check['block']:
                result['skipped'].append({
                    'login': login,
                    'reason': check['block_reason'],
                    'detail': check['block_detail'],
                })
                continue
            if not _process_warnings(check, login, force, result):
                continue

            _, created = OfferPoolItem.objects.get_or_create(
                pool=pool,
                owned_product=owned,
                defaults={'order': max_order + i},
            )
            if created:
                result['added'] += 1

        return result['added']

    # Legacy fallback: no spec and no preset found, use platform credential map
    mapping = _PLATFORM_CREDENTIAL_MAP.get(platform)

    for i, cred in enumerate(credentials):
        if mapping:
            login_key, pass_key, extra_keys = mapping
            login = cred.get(login_key, '').strip().lower()
            password = cred.get(pass_key, '').strip()
            credential_extras = {}
            for k in extra_keys:
                val = cred.get(k, '').strip()
                if val:
                    credential_extras[k] = val
        else:
            login = cred.get('login', '').strip().lower()
            password = cred.get('password', '').strip()
            credential_extras = {}

        if not login or not password:
            continue

        raw_data = {
            'source': 'manual',
            'main_platform': platform,
            'loginData': {'login': login, 'password': password},
            'emailLoginData': {
                'login': cred.get('email', '').strip(),
                'password': cred.get('email_password', '').strip(),
            },
            'security_email': cred.get('security_email', '').strip(),
            'security_email_password': cred.get('security_email_password', '').strip(),
            'security_email_login_link': cred.get('security_email_login_link', '').strip(),
            'birthday': cred.get('birthday', cred.get('dob', '')).strip(),
            'emailLoginUrl': cred.get('email_login_link', '').strip(),
            'item_id': f'manual-{uuid.uuid4().hex[:12]}',
        }

        if credential_extras:
            raw_data.update(credential_extras)

        extra_fields = {
            'email': cred.get('email', '').strip(),
            'email_password': cred.get('email_password', '').strip(),
            'email_login_link': cred.get('email_login_link', '').strip(),
            'security_email': cred.get('security_email', '').strip(),
            'security_email_password': cred.get('security_email_password', '').strip(),
        }

        owned, _ = _get_or_create_owned_product(
            game, login, password,
            ref_price=ref_price,
            extra_fields=extra_fields,
            raw_data=raw_data,
        )

        # Validate before adding to pool
        check = _validate_pool_candidate(owned, pool)
        if check['block']:
            result['skipped'].append({
                'login': login,
                'reason': check['block_reason'],
                'detail': check['block_detail'],
            })
            continue
        if not _process_warnings(check, login, force, result):
            continue

        _, created = OfferPoolItem.objects.get_or_create(
            pool=pool,
            owned_product=owned,
            defaults={'order': max_order + i},
        )
        if created:
            result['added'] += 1

    return result['added']
