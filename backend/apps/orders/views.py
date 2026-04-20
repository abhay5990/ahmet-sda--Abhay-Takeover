import json
import logging

from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount, Provider
from apps.inventory.models import Game
from .models import Order
from .enums import OrderStatus

logger = logging.getLogger(__name__)

BULK_LIMIT = 100
_VALID_STATUSES = {s.value for s in OrderStatus}


@role_required('admin', 'user', 'viewer')
def order_list(request):
    """Order browser with filters and search."""
    orders = Order.objects.select_related(
        'integration_account',
        'game',
        'owned_product',
    ).defer(
        'raw_data',
        'owned_product__password',
        'owned_product__email_password',
        'owned_product__security_email_password',
        'owned_product__password_hash',
        'owned_product__email_login_link',
        'owned_product__security_email',
        'owned_product__security_email_login_link',
        'owned_product__raw_data',
    ).order_by('-sold_at', '-created_at')

    # --- Filters ---
    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)

    provider = request.GET.get('provider')
    if provider:
        orders = orders.filter(integration_account__provider=provider)

    account_id = request.GET.get('account')
    if account_id:
        orders = orders.filter(integration_account_id=account_id)

    game_id = request.GET.get('game')
    if game_id:
        orders = orders.filter(game_id=game_id)

    is_instant = request.GET.get('instant')
    if is_instant == '1':
        orders = orders.filter(is_instant=True)
    elif is_instant == '0':
        orders = orders.filter(is_instant=False)

    # --- Search ---
    search = request.GET.get('q', '').strip()
    if search:
        orders = orders.filter(
            Q(store_order_id__icontains=search)
            | Q(owned_product__login__icontains=search)
            | Q(store_listing_id__icontains=search)
        )

    # --- Stats ---
    stats_qs = Order.objects.values('status').annotate(cnt=Count('id'))
    stats_map = {row['status']: row['cnt'] for row in stats_qs}
    stats_items = [
        {'label': 'Pending', 'value': stats_map.get('pending', 0), 'color': 'yellow'},
        {'label': 'Delivered', 'value': stats_map.get('delivered', 0), 'color': 'blue'},
        {'label': 'Completed', 'value': stats_map.get('completed', 0), 'color': 'emerald'},
        {'label': 'Disputed', 'value': stats_map.get('disputed', 0), 'color': 'red'},
        {'label': 'Cancelled', 'value': stats_map.get('cancelled', 0), 'color': 'gray'},
    ]

    # --- Pagination ---
    paginator = Paginator(orders, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'orders/order_list.html', {
        'page_obj': page_obj,
        'stats_items': stats_items,
        'statuses': OrderStatus.choices,
        'providers': Provider.choices,
        'accounts': IntegrationAccount.objects.filter(is_active=True).order_by('provider', 'name'),
        'games': Game.objects.filter(is_active=True).order_by('name'),
        'selected_status': status or '',
        'selected_provider': provider or '',
        'selected_account': account_id or '',
        'selected_game': game_id or '',
        'selected_instant': is_instant or '',
        'instant_types': [('1', 'Instant'), ('0', 'Manual / Dropship')],
        'search_query': search,
    })


@role_required('admin', 'user')
def order_update_status(request, order_id):
    """PATCH: Update a single order's status (DB-only)."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    new_status = data.get('status', '').strip()
    if new_status not in _VALID_STATUSES:
        return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)

    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

    old_status = order.status
    order.status = new_status
    order.save(update_fields=['status'])
    logger.info("Order %s status: %s -> %s (by %s)", order_id, old_status, new_status, request.user)

    return JsonResponse({'ok': True, 'old_status': old_status, 'new_status': new_status})


@role_required('admin', 'user')
@require_POST
def order_bulk_update_status(request):
    """POST: Bulk update order statuses (DB-only)."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ids = data.get('ids', [])
    new_status = data.get('status', '').strip()

    if not ids or len(ids) > BULK_LIMIT:
        return JsonResponse({'error': f'Provide 1-{BULK_LIMIT} ids'}, status=400)
    if new_status not in _VALID_STATUSES:
        return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)

    updated = Order.objects.filter(pk__in=ids).update(status=new_status)
    logger.info("Bulk order status -> %s: %d/%d updated (by %s)", new_status, updated, len(ids), request.user)

    return JsonResponse({'ok': True, 'updated': updated})
