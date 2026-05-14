import json
import logging

from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount
from apps.listings.models import Listing
from .enums import DropshipProductStatus, OwnedProductStatus
from .models import Category, DropshipProduct, Game, OwnedProduct

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
BULK_LIMIT = 100
_VALID_OWNED_STATUSES = {s.value for s in OwnedProductStatus}
_VALID_DROPSHIP_STATUSES = {s.value for s in DropshipProductStatus}


def _apply_owned_product_filters(request, queryset):
    """Apply standard OwnedProduct filters from GET params. Returns (queryset, filter_state)."""
    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(Q(login__icontains=search))

    status = request.GET.get('status')
    if status:
        queryset = queryset.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        queryset = queryset.filter(game_id=game_id)

    category_id = request.GET.get('category')
    if category_id:
        queryset = queryset.filter(category_id=category_id)

    missing_on = request.GET.get('missing_on')
    if missing_on:
        _active_listings = ['listed', 'paused']
        has_on_target = Listing.objects.filter(
            listing_owned_products__owned_product=OuterRef('pk'),
            integration_account_id=missing_on,
            status__in=_active_listings,
        )
        has_on_any_other = Listing.objects.filter(
            listing_owned_products__owned_product=OuterRef('pk'),
            status__in=_active_listings,
        ).exclude(integration_account_id=missing_on)
        queryset = queryset.filter(
            status__in=['draft', 'listed'],
        ).filter(
            Exists(has_on_any_other),
        ).exclude(
            Exists(has_on_target),
        )

    return queryset, {
        'search': search, 'status': status or '',
        'game_id': game_id or '', 'category_id': category_id or '',
        'missing_on': missing_on or '',
    }


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

    products, fs = _apply_owned_product_filters(request, products)

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

    sell_stores = [
        (str(s.id), str(s))
        for s in IntegrationAccount.objects.filter(
            is_active=True, role__in=['sell', 'both'],
        ).order_by('provider', 'name')
    ]

    paginator = Paginator(products, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'inventory/product_list.html', {
        'page_obj': page_obj,
        'stats_items': stats_items,
        'games': Game.objects.filter(is_active=True).order_by('name'),
        'categories': [(str(c.id), c.title) for c in Category.objects.order_by('title')],
        'statuses': OwnedProductStatus.choices,
        'stores': sell_stores,
        'selected_game': fs['game_id'],
        'selected_category': fs['category_id'],
        'selected_status': fs['status'],
        'selected_missing_on': fs['missing_on'],
        'search_query': fs['search'],
        'has_sheets_credential': _is_admin(request) and _has_sheets_credential(),
    })


@role_required('admin', 'user', 'viewer')
def product_detail(request, product_id):
    """OwnedProduct detail page with related orders and listings."""
    product = get_object_or_404(
        OwnedProduct.objects.select_related('game', 'category', 'source_account', 'product_origin'),
        pk=product_id,
    )

    orders = product.orders.select_related(
        'integration_account', 'listing',
    ).order_by('-created_at')

    listings = Listing.objects.filter(
        listing_owned_products__owned_product=product,
    ).select_related('integration_account', 'game').order_by('-created_at')

    return render(request, 'inventory/product_detail.html', {
        'product': product,
        'orders': orders,
        'listings': listings,
        'statuses': OwnedProductStatus.choices,
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


# ── Google Sheets Export ──


def _is_admin(request) -> bool:
    u = request.user
    return u.is_authenticated and (u.is_superuser or getattr(u, 'role', '') == 'admin')


def _has_sheets_credential() -> bool:
    from .services.sheets_export import get_google_sheets_credential
    return get_google_sheets_credential() is not None


@role_required('admin')
@require_POST
def export_to_sheet(request):
    """POST: Export filtered OwnedProducts to a Google Sheet."""
    from .services.sheets_export import (
        ALL_EXTRA_KEYS,
        SheetsExportService,
        get_google_sheets_credential,
    )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    spreadsheet_id = (data.get('spreadsheet_id') or '').strip()
    sheet_name = (data.get('sheet_name') or '').strip()
    extra_fields = data.get('extra_fields', [])
    row_limit = int(data.get('limit', 0) or 0)

    if not spreadsheet_id:
        return JsonResponse({'error': 'spreadsheet_id is required'}, status=400)
    if not sheet_name:
        return JsonResponse({'error': 'sheet_name is required'}, status=400)
    if not isinstance(extra_fields, list):
        return JsonResponse({'error': 'extra_fields must be a list'}, status=400)

    # Validate extra field keys
    invalid = set(extra_fields) - ALL_EXTRA_KEYS
    if invalid:
        return JsonResponse({'error': f'Invalid extra fields: {", ".join(invalid)}'}, status=400)

    # Get credential
    credential = get_google_sheets_credential()
    if not credential:
        return JsonResponse({'error': 'No active Google Sheets credential configured.'}, status=400)

    # Build filtered queryset (same filters as the list page)
    queryset = OwnedProduct.objects.select_related(
        'game', 'category', 'source_account',
    ).order_by('-created_at')
    queryset, _fs = _apply_owned_product_filters(request, queryset)

    try:
        svc = SheetsExportService.from_credential(credential)
        count = svc.export(queryset, spreadsheet_id, sheet_name, extra_fields, limit=row_limit)
    except Exception as exc:
        logger.exception("Google Sheets export failed")
        msg = str(exc)
        if 'not found' in msg.lower() or 'PERMISSION_DENIED' in msg:
            msg = f"Cannot access spreadsheet. Make sure it's shared with the service account. ({msg})"
        return JsonResponse({'error': msg}, status=500)

    return JsonResponse({'ok': True, 'rows_exported': count})
