import json
import logging

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from .enums import DropshipProductStatus, OwnedProductStatus
from .models import Category, DropshipProduct, Game, OwnedProduct

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
BULK_LIMIT = 100
_VALID_OWNED_STATUSES = {s.value for s in OwnedProductStatus}
_VALID_DROPSHIP_STATUSES = {s.value for s in DropshipProductStatus}


@role_required('admin', 'user', 'viewer')
def index(request):
    """OwnedProduct browser with filters and pagination."""
    products = OwnedProduct.objects.select_related(
        'game', 'category', 'source_account',
    ).defer(
        'password', 'email_password', 'security_email_password',
        'password_hash', 'email_login_link',
        'security_email', 'security_email_login_link',
        'raw_data',
    ).order_by('-created_at')

    # Search
    search = request.GET.get('q', '').strip()
    if search:
        products = products.filter(Q(login__icontains=search))

    # Filters
    status = request.GET.get('status')
    if status:
        products = products.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        products = products.filter(game_id=game_id)

    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category_id=category_id)

    # Stats
    stats_qs = OwnedProduct.objects.values('status').annotate(cnt=Count('id'))
    stats_map = {row['status']: row['cnt'] for row in stats_qs}
    stats_items = [
        {'label': 'Draft', 'value': stats_map.get('draft', 0), 'color': 'gray'},
        {'label': 'Listed', 'value': stats_map.get('listed', 0), 'color': 'blue'},
        {'label': 'Sold', 'value': stats_map.get('sold', 0) + stats_map.get('multiple_sold', 0), 'color': 'emerald'},
        {'label': 'Lost', 'value': stats_map.get('lost', 0), 'color': 'orange'},
        {'label': 'Banned', 'value': stats_map.get('banned', 0), 'color': 'red'},
    ]

    paginator = Paginator(products, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'inventory/product_list.html', {
        'page_obj': page_obj,
        'stats_items': stats_items,
        'games': Game.objects.filter(is_active=True).order_by('name'),
        'categories': [(str(c.id), c.title) for c in Category.objects.order_by('title')],
        'statuses': OwnedProductStatus.choices,
        'selected_game': game_id or '',
        'selected_category': category_id or '',
        'selected_status': status or '',
        'search_query': search,
    })


@role_required('admin', 'user', 'viewer')
def dropship_list(request):
    """DropshipProduct browser with filters and pagination."""
    products = DropshipProduct.objects.select_related(
        'game', 'category', 'source_account',
    ).order_by('-created_at')

    # Search
    search = request.GET.get('q', '').strip()
    if search:
        products = products.filter(Q(product_title__icontains=search))

    # Filters
    status = request.GET.get('status')
    if status:
        products = products.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        products = products.filter(game_id=game_id)

    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category_id=category_id)

    # Stats
    ds_stats_qs = DropshipProduct.objects.values('status').annotate(cnt=Count('id'))
    ds_stats_map = {row['status']: row['cnt'] for row in ds_stats_qs}
    stats_items = [
        {'label': 'Listed', 'value': ds_stats_map.get('listed', 0), 'color': 'blue'},
        {'label': 'Sold', 'value': ds_stats_map.get('sold', 0), 'color': 'emerald'},
        {'label': 'Deleted', 'value': ds_stats_map.get('deleted', 0), 'color': 'red'},
    ]

    paginator = Paginator(products, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'inventory/dropship_list.html', {
        'page_obj': page_obj,
        'stats_items': stats_items,
        'games': Game.objects.filter(is_active=True).order_by('name'),
        'categories': [(str(c.id), c.title) for c in Category.objects.order_by('title')],
        'statuses': DropshipProductStatus.choices,
        'selected_game': game_id or '',
        'selected_category': category_id or '',
        'selected_status': status or '',
        'search_query': search,
    })


# ── Inventory API endpoints (DB-only status updates) ──


@role_required('admin', 'user')
def owned_product_update_status(request, product_id):
    """PATCH: Update a single OwnedProduct's status."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    new_status = data.get('status', '').strip()
    if new_status not in _VALID_OWNED_STATUSES:
        return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)

    try:
        product = OwnedProduct.objects.get(pk=product_id)
    except OwnedProduct.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

    old_status = product.status
    product.status = new_status
    product.save(update_fields=['status'])
    logger.info("OwnedProduct %s status: %s -> %s (by %s)", product_id, old_status, new_status, request.user)

    return JsonResponse({'ok': True, 'old_status': old_status, 'new_status': new_status})


@role_required('admin', 'user')
@require_POST
def owned_product_bulk_update_status(request):
    """POST: Bulk update OwnedProduct statuses."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ids = data.get('ids', [])
    new_status = data.get('status', '').strip()

    if not ids or len(ids) > BULK_LIMIT:
        return JsonResponse({'error': f'Provide 1-{BULK_LIMIT} ids'}, status=400)
    if new_status not in _VALID_OWNED_STATUSES:
        return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)

    updated = OwnedProduct.objects.filter(pk__in=ids).update(status=new_status)
    logger.info("Bulk OwnedProduct status -> %s: %d/%d (by %s)", new_status, updated, len(ids), request.user)

    return JsonResponse({'ok': True, 'updated': updated})


@role_required('admin', 'user')
def dropship_product_update_status(request, product_id):
    """PATCH: Update a single DropshipProduct's status."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    new_status = data.get('status', '').strip()
    if new_status not in _VALID_DROPSHIP_STATUSES:
        return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)

    try:
        product = DropshipProduct.objects.get(pk=product_id)
    except DropshipProduct.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

    old_status = product.status
    product.status = new_status
    product.save(update_fields=['status'])
    logger.info("DropshipProduct %s status: %s -> %s (by %s)", product_id, old_status, new_status, request.user)

    return JsonResponse({'ok': True, 'old_status': old_status, 'new_status': new_status})


@role_required('admin', 'user')
@require_POST
def dropship_product_bulk_update_status(request):
    """POST: Bulk update DropshipProduct statuses."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ids = data.get('ids', [])
    new_status = data.get('status', '').strip()

    if not ids or len(ids) > BULK_LIMIT:
        return JsonResponse({'error': f'Provide 1-{BULK_LIMIT} ids'}, status=400)
    if new_status not in _VALID_DROPSHIP_STATUSES:
        return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)

    updated = DropshipProduct.objects.filter(pk__in=ids).update(status=new_status)
    logger.info("Bulk DropshipProduct status -> %s: %d/%d (by %s)", new_status, updated, len(ids), request.user)

    return JsonResponse({'ok': True, 'updated': updated})
