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
from .utils import parse_price

_ACTIVE_LISTING_STATUSES = ['listed', 'paused']

logger = logging.getLogger(__name__)

BULK_DELETE_LIMIT = 100
_DELETABLE_STATUSES = {ListingStatus.LISTED, ListingStatus.PAUSED}


def _get_listing_url(listing) -> str:
    """Build the marketplace URL for a listing."""
    if not listing.store_listing_id or not listing.integration_account:
        return ''
    provider = listing.integration_account.provider
    sid = listing.store_listing_id
    if provider == 'eldorado':
        return f'https://www.eldorado.gg/sell/offers/{sid}'
    if provider == 'gameboost':
        return f'https://gameboost.com/sell/offers/{sid}'
    if provider == 'playerauctions':
        return f'https://www.playerauctions.com/offer/{sid}/'
    return ''


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
    # [DETAIL-ENHANCED]
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

    from apps.posting.models import PoolOffer
    from apps.listings.models import ListingOwnedProduct
    pool_offer = (
        PoolOffer.objects.filter(listing=listing)
        .select_related('pool', 'pool__game', 'listing__integration_account')
        .first()
    )
    offer_pool = pool_offer.pool if pool_offer else None

    # Build sibling listings — other listings sharing the same owned products
    sibling_listings = []
    if owned_products:
        op_ids = [op.id for op in owned_products]
        siblings_qs = (
            Listing.objects
            .filter(listing_owned_products__owned_product_id__in=op_ids)
            .exclude(id=listing.id)
            .select_related('integration_account')
            .distinct()
            .order_by('integration_account__provider', 'integration_account__name', 'id')
        )
        from collections import defaultdict
        grouped = defaultdict(list)
        for s in siblings_qs:
            provider = s.integration_account.provider if s.integration_account else 'unknown'
            grouped[provider].append({
                'id': s.id,
                'store_listing_id': s.store_listing_id,
                'store_name': s.integration_account.name if s.integration_account else '',
                'store_id': s.integration_account.id if s.integration_account else None,
                'status': s.status,
                'price': str(s.price) if s.price is not None else '',
                'title': s.title or '',
                'url': _get_listing_url(s),
            })
        sibling_listings = [
            {'provider': provider, 'listings': items}
            for provider, items in sorted(grouped.items())
        ]

    # PA store accounts for "Add to PA" button
    pa_stores = list(
        IntegrationAccount.objects.filter(
            provider='playerauctions', is_active=True, role__in=['sell', 'both'],
        ).order_by('name')
    )

    return render(request, 'listings/listing_detail.html', {
        'listing': listing,
        'owned_products': owned_products,
        'offer_pool': offer_pool,
        'pool_offer': pool_offer,
        'sibling_listings': sibling_listings,
        'pa_stores': pa_stores,
    })


@role_required('admin', 'user')
@require_POST
def listing_remove_key(request, listing_id, product_id):
    """Remove one linked key, including its remote credential when required."""
    listing = get_object_or_404(
        Listing.objects.select_related('integration_account'),
        pk=listing_id,
    )
    link = get_object_or_404(
        ListingOwnedProduct.objects.select_related('owned_product'),
        listing=listing,
        owned_product_id=product_id,
    )

    from apps.posting.models import OfferPoolItem
    from apps.posting.services.pool.lifecycle import remove_pool_item

    pool_item = (
        OfferPoolItem.objects.filter(owned_product_id=product_id)
        .filter(
            Q(pool_offer__listing=listing)
            | Q(active_offers__listing=listing)
        )
        .select_related('pool_offer', 'owned_product')
        .distinct()
        .first()
    )

    if pool_item and pool_item.pool_offer_id:
        result = remove_pool_item(
            pool_item.pool_offer,
            pool_item,
            listing=listing,
        )
        if not result.ok:
            return JsonResponse(
                {'error': '; '.join(result.errors) or 'Key removal failed'},
                status=409,
            )
        return JsonResponse({
            'ok': True,
            'remote_removed': result.remote_removed,
            'message': 'Key removed from this listing.',
        })

    if listing.status in _ACTIVE_LISTING_STATUSES:
        return JsonResponse({
            'error': (
                'This active listing is not managed by an Auto-Restock Pool, '
                'so the remote key cannot be removed safely from here.'
            ),
        }, status=409)

    link.delete()
    return JsonResponse({
        'ok': True,
        'remote_removed': False,
        'message': 'Key link removed from this inactive listing.',
    })


@role_required('admin', 'user')
def listing_edit(request, listing_id):
    """GET: return current title/description/price. POST: edit on marketplace."""
    try:
        listing = Listing.objects.select_related(
            'integration_account', 'integration_account__credential',
        ).get(id=listing_id)
    except Listing.DoesNotExist:
        return JsonResponse({'error': 'Listing not found'}, status=404)

    if request.method == 'GET':
        raw = listing.raw_data or {}
        return JsonResponse({
            'title': listing.title or '',
            'description': raw.get('description', ''),
            'price': str(listing.price) if listing.price is not None else '',
        })

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if listing.status not in {'listed', 'paused'}:
        return JsonResponse(
            {'error': f'Cannot edit a listing with status "{listing.status}"'},
            status=422,
        )

    changes = {}
    if 'title' in body:
        title = str(body['title']).strip() if body['title'] else ''
        if not title:
            return JsonResponse({'error': 'title cannot be empty'}, status=400)
        changes['title'] = title
    if 'description' in body:
        description = str(body['description']).strip() if body['description'] else ''
        if not description:
            return JsonResponse({'error': 'description cannot be empty'}, status=400)
        changes['description'] = description
    if 'price' in body and body['price'] is not None:
        try:
            changes['price'] = parse_price(body['price'])
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    if not changes:
        return JsonResponse({'error': 'No changes provided'}, status=400)

    from apps.posting.services.offer_editor import edit_offer
    result = edit_offer(listing, changes)

    if result.ok:
        return JsonResponse({
            'ok': True,
            'new_offer_id': result.new_offer_id or listing.store_listing_id,
        })
    return JsonResponse({'error': result.error}, status=422)


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
