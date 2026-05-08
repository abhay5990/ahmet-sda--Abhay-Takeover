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
from apps.listings.models import Listing
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
    added = 0
    if credentials:
        added = _add_credentials_to_pool(pool, credentials, game, listing=listing)

    # Activate pool if items were added
    if added > 0 and pool.status == OfferPoolStatus.DEPLETED:
        pool.status = OfferPoolStatus.ACTIVE
        pool.save(update_fields=['status', 'updated_at'])

    pool.refresh_from_db()
    return JsonResponse({
        'pool': _pool_to_dict(pool),
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
    """Add credentials to a pool.

    POST body (JSON):
        credentials: list[dict]  — [{login, password, email?, ...}]
    OR:
        owned_product_ids: list[int] — existing OwnedProduct IDs to add
    """
    try:
        pool = OfferPool.objects.select_related('game', 'listing').get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    added = 0

    # Mode 1: raw credentials → create OwnedProducts + add to pool
    credentials = body.get('credentials', [])
    if credentials:
        added = _add_credentials_to_pool(pool, credentials, pool.game, listing=pool.listing)

    # Mode 2: existing OwnedProduct IDs
    owned_product_ids = body.get('owned_product_ids', [])
    if owned_product_ids:
        products = OwnedProduct.objects.filter(id__in=owned_product_ids)
        max_order = pool.items.count()
        for i, product in enumerate(products):
            _, created = OfferPoolItem.objects.get_or_create(
                pool=pool,
                owned_product=product,
                defaults={'order': max_order + i},
            )
            if created:
                added += 1

    # Re-activate pool if it was depleted and we added items
    if added > 0 and pool.status == OfferPoolStatus.DEPLETED:
        pool.status = OfferPoolStatus.ACTIVE
        pool.save(update_fields=['status', 'updated_at'])

    pool.refresh_from_db()
    return JsonResponse({'added': added, 'total_pending': pool.pending_count})


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
            'sub_platform': lst.sub_platform,
            'created_at': lst.created_at.isoformat(),
        })

    return JsonResponse({'listings': data, 'total': total})


# ── Serializers ──────────────────────────────────────────────────


def _pool_to_dict(pool: OfferPool) -> dict:
    pending = pool.items.filter(status=OfferPoolItemStatus.PENDING).count()
    pushed = pool.items.filter(status=OfferPoolItemStatus.PUSHED).count()
    failed = pool.items.filter(status=OfferPoolItemStatus.FAILED).count()

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
        'items_total': pending + pushed + failed,
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


# Platform-specific credential key mappings (same as stock.py)
_PLATFORM_CREDENTIAL_MAP: dict[str, tuple[str, str, tuple[str, ...]]] = {
    'PlayStation 4':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'PlayStation 5':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'Xbox One':        ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'Xbox Series X/S': ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'PC - Legacy':     ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
    'PC - Enhanced':   ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
}


def _add_credentials_to_pool(
    pool: OfferPool,
    credentials: list[dict],
    game: Game,
    listing: Listing | None = None,
) -> int:
    """Create OwnedProducts from raw credentials and add as OfferPoolItems."""
    added = 0
    max_order = pool.items.count()

    # Resolve platform from listing's sub_platform (stored as full name)
    platform = (listing.sub_platform or '') if listing else ''

    # Get reference price from listing's existing owned products
    ref_price = None
    if listing:
        from apps.listings.models import ListingOwnedProduct
        ref_lop = (
            ListingOwnedProduct.objects
            .filter(listing=listing, owned_product__price__isnull=False)
            .select_related('owned_product')
            .first()
        )
        if ref_lop:
            ref_price = ref_lop.owned_product.price

    mapping = _PLATFORM_CREDENTIAL_MAP.get(platform)

    for i, cred in enumerate(credentials):
        # Extract login/password using platform mapping
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

        # Build raw_data (LZT-compatible format)
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

        # Store platform-specific extras in raw_data
        if credential_extras:
            raw_data.update(credential_extras)

        owned, _ = OwnedProduct.objects.update_or_create(
            category=game.category,
            login=login,
            defaults={
                'password': password,
                'password_hash': hashlib.sha256(password.encode()).hexdigest(),
                'email': cred.get('email', '').strip(),
                'email_password': cred.get('email_password', '').strip(),
                'email_login_link': cred.get('email_login_link', '').strip(),
                'security_email': cred.get('security_email', '').strip(),
                'security_email_password': cred.get('security_email_password', '').strip(),
                'game': game,
                'price': ref_price,
                'status': 'draft',
                'raw_data': raw_data,
            },
        )

        _, created = OfferPoolItem.objects.get_or_create(
            pool=pool,
            owned_product=owned,
            defaults={'order': max_order + i},
        )
        if created:
            added += 1

    return added
