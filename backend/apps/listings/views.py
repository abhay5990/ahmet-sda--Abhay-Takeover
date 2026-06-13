import json
import logging

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import Coalesce, Greatest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Game, OwnedProduct
from apps.posting.services.dropship.delist import _delete_one_listing
from apps.posting.services.relist import relist_listing
from .enums import ListingStatus
from .models import Listing, ListingOwnedProduct

_ACTIVE_LISTING_STATUSES = ['listed', 'paused']

logger = logging.getLogger(__name__)

BULK_DELETE_LIMIT = 100
_DELETABLE_STATUSES = {ListingStatus.LISTED, ListingStatus.PAUSED}


@role_required('admin', 'user')
def listing_list(request):
    """Listing browser with filters and pagination."""
    _lop_prefetch = Prefetch(
        'listing_owned_products',
        queryset=ListingOwnedProduct.objects.select_related('owned_product').only(
            'id', 'listing_id', 'owned_product__id', 'owned_product__login',
        ),
    )

    listings = Listing.objects.select_related(
        'game', 'integration_account', 'dropship_product',
    ).prefetch_related(
        _lop_prefetch,
    ).defer('raw_data').annotate(
        last_action_at=Coalesce(
            Greatest('listed_at', 'removed_at'),
            'listed_at',
            'removed_at',
            'created_at',
        ),
    ).order_by('-last_action_at')

    # Filters
    status = request.GET.get('status')
    if status:
        listings = listings.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        listings = listings.filter(game_id=game_id)

    store_id = request.GET.get('store')
    if store_id:
        listings = listings.filter(integration_account_id=store_id)

    is_instant = request.GET.get('is_instant')
    if is_instant == 'true':
        listings = listings.filter(is_instant=True)
    elif is_instant == 'false':
        listings = listings.filter(is_instant=False)

    q = request.GET.get('q', '').strip()
    if q:
        q_filter = (
            Q(title__icontains=q)
            | Q(store_listing_id__icontains=q)
            | Q(listing_owned_products__owned_product__login__icontains=q)
        )
        try:
            q_int = int(q)
            q_filter |= Q(dropship_product__source_product_id=q_int)
        except ValueError:
            pass
        listings = listings.filter(q_filter).distinct()

    # "Missing on store" — active listings whose linked OwnedProducts
    # do NOT have an active listing on the selected target store.
    missing_on = request.GET.get('missing_on')
    if missing_on:
        products_on_target = ListingOwnedProduct.objects.filter(
            listing__integration_account_id=missing_on,
            listing__status__in=_ACTIVE_LISTING_STATUSES,
        ).values('owned_product_id')
        listings = listings.filter(
            status__in=_ACTIVE_LISTING_STATUSES,
        ).exclude(
            integration_account_id=missing_on,
        ).exclude(
            listing_owned_products__owned_product_id__in=products_on_target,
        )

    # Stats (global, not filtered)
    all_status_counts = dict(
        Listing.objects.order_by().values('status').annotate(n=Count('id')).values_list('status', 'n')
    )
    stats_items = [
        {'label': 'Listed', 'value': all_status_counts.get('listed', 0), 'color': 'emerald'},
        {'label': 'Paused', 'value': all_status_counts.get('paused', 0), 'color': 'yellow'},
        {'label': 'Closed', 'value': all_status_counts.get('closed', 0), 'color': 'gray'},
        {'label': 'Deleted', 'value': all_status_counts.get('deleted', 0), 'color': 'red'},
    ]

    games = Game.objects.filter(is_active=True).order_by('name')
    stores = IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).order_by('provider', 'name')
    missing_on_stores = [(str(s.id), str(s)) for s in stores]

    paginator = Paginator(listings, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'listings/listing_list.html', {
        'page_obj': page_obj,
        'stats_items': stats_items,
        'listing_statuses': ListingStatus.choices,
        'instant_types': [('true', 'Instant'), ('false', 'Manual')],
        'games': games,
        'stores': stores,
        'missing_on_stores': missing_on_stores,
        'selected_status': status or '',
        'selected_game': game_id or '',
        'selected_store': store_id or '',
        'selected_is_instant': is_instant or '',
        'selected_missing_on': missing_on or '',
        'q': q,
    })


@role_required('admin', 'user')
def listing_detail(request, listing_id):
    """Detail page for a single listing."""
    listing = get_object_or_404(
        Listing.objects.select_related(
            'game', 'integration_account', 'dropship_product',
            'dropship_product__source_account',
        ),
        id=listing_id,
    )

    owned_products = list(
        OwnedProduct.objects.filter(
            listing_owned_products__listing_id=listing.id,
        ).select_related('game', 'category').order_by('login')
    )

    offer_pool = (
        listing.offer_pools
        .select_related('store', 'game')
        .prefetch_related('items')
        .first()
    )

    return render(request, 'listings/listing_detail.html', {
        'listing': listing,
        'owned_products': owned_products,
        'offer_pool': offer_pool,
    })


@role_required('admin', 'user')
def listing_delete(request, listing_id):
    """DELETE a single listing from the marketplace and mark it DELETED locally."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        listing = Listing.objects.select_related(
            'integration_account', 'integration_account__credential',
        ).get(id=listing_id)
    except Listing.DoesNotExist:
        return JsonResponse({'error': 'Listing not found'}, status=404)

    if listing.status not in _DELETABLE_STATUSES:
        return JsonResponse(
            {'error': f'Cannot delete a listing with status "{listing.status}"'},
            status=422,
        )

    ok = _delete_one_listing(listing)
    if ok:
        return JsonResponse({'ok': True})
    return JsonResponse({'error': 'Failed to remove marketplace offer'}, status=422)


@role_required('admin', 'user')
@require_POST
def listing_bulk_delete(request):
    """Bulk delete up to BULK_DELETE_LIMIT listings."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ids = body.get('ids', [])
    if not ids or not isinstance(ids, list):
        return JsonResponse({'error': 'ids must be a non-empty list'}, status=400)

    if len(ids) > BULK_DELETE_LIMIT:
        return JsonResponse(
            {'error': f'Maximum {BULK_DELETE_LIMIT} listings per bulk action'},
            status=400,
        )

    listings = list(
        Listing.objects.select_related(
            'integration_account', 'integration_account__credential',
        ).filter(id__in=ids, status__in=_DELETABLE_STATUSES)
    )

    if not listings:
        return JsonResponse({'error': 'No deletable listings found'}, status=404)

    succeeded: list[int] = []
    failed: list[int] = []
    errors: dict[str, str] = {}

    for listing in listings:
        ok = _delete_one_listing(listing)
        if ok:
            succeeded.append(listing.id)
        else:
            failed.append(listing.id)
            store_name = listing.integration_account.name if listing.integration_account else 'unknown'
            errors[str(listing.id)] = f'Failed to remove offer on {store_name}'

    status_code = 200 if not failed else 207
    return JsonResponse({
        'ok': len(failed) == 0,
        'succeeded': succeeded,
        'failed': failed,
        'errors': errors,
    }, status=status_code)


BULK_RELIST_LIMIT = 50
_RELISTABLE_STATUSES = {ListingStatus.LISTED, ListingStatus.PAUSED, ListingStatus.DELETED}


@role_required('admin', 'user')
@require_POST
def listing_relist(request, listing_id):
    """Delete a listing from the marketplace and re-create it (fresh expiry)."""
    try:
        listing = Listing.objects.select_related(
            'integration_account', 'integration_account__credential',
        ).get(id=listing_id)
    except Listing.DoesNotExist:
        return JsonResponse({'error': 'Listing not found'}, status=404)

    if listing.status not in _RELISTABLE_STATUSES:
        return JsonResponse(
            {'error': f'Cannot relist a listing with status "{listing.status}"'},
            status=422,
        )

    result = relist_listing(listing)
    if result.ok:
        return JsonResponse({
            'ok': True,
            'new_listing_id': result.new_listing.id,
        })
    return JsonResponse({'error': result.error}, status=422)


@role_required('admin', 'user')
@require_POST
def listing_bulk_relist(request):
    """Bulk relist up to BULK_RELIST_LIMIT listings."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ids = body.get('ids', [])
    if not ids or not isinstance(ids, list):
        return JsonResponse({'error': 'ids must be a non-empty list'}, status=400)

    if len(ids) > BULK_RELIST_LIMIT:
        return JsonResponse(
            {'error': f'Maximum {BULK_RELIST_LIMIT} listings per bulk relist'},
            status=400,
        )

    listings = list(
        Listing.objects.select_related(
            'integration_account', 'integration_account__credential',
        ).filter(id__in=ids, status__in=_RELISTABLE_STATUSES)
    )

    if not listings:
        return JsonResponse({'error': 'No relistable listings found'}, status=404)

    succeeded: list[int] = []
    failed: list[int] = []
    errors: dict[str, str] = {}

    for listing in listings:
        result = relist_listing(listing)
        if result.ok:
            succeeded.append(result.new_listing.id)
        else:
            failed.append(listing.id)
            errors[str(listing.id)] = result.error

    status_code = 200 if not failed else 207
    return JsonResponse({
        'ok': len(failed) == 0,
        'succeeded': succeeded,
        'failed': failed,
        'errors': errors,
    }, status=status_code)
