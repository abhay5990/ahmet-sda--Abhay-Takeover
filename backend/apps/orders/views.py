import json
import logging

from django.db import transaction
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount, Provider
from apps.inventory.enums import OwnedProductStatus
from apps.inventory.models import Game
from apps.posting.models import OfferPoolItem, OfferPoolItemStatus
from .models import Order, OrderReplacement
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
    ).prefetch_related(
        'replacements',  # for the "Replaced" badge/tooltip on the row
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


@role_required('admin', 'user')
@require_POST
@transaction.atomic
def order_replace(request, order_id):
    """Swap a self-owned manual-entry order from the UNALLOCATED pool.

    Only manual-entry accounts qualify (auto-sourced/dropship accounts are
    unique and must never be replaced). The replacement is drawn exclusively
    from the same pool's unallocated pending stock — items on no marketplace —
    so there is no delist, no race window, and no possibility of a double-sale.
    """
    order = get_object_or_404(
        Order.objects.select_for_update().select_related('owned_product'),
        pk=order_id,
    )

    # 1. Eligibility — explicit manual-entry, self-owned account only
    # (re-checked server-side).  ``is_instant=False`` is the authoritative
    # manual-entry classification.  The absence of an owned-product FK is
    # handled safely below with 409 because legacy manual imports may not have
    # persisted that link.
    if order.is_instant or order.dropship_product_id:
        return JsonResponse(
            {'ok': False, 'error': 'Replacement is only available for self-owned manual-entry accounts.'},
            status=400,
        )

    reason = (request.POST.get('reason') or '').strip()
    employee_name = (request.POST.get('employee_name') or '').strip()
    if len(reason) < 3 or not employee_name:
        return JsonResponse(
            {'ok': False, 'error': 'Reason and employee name are required.'},
            status=400,
        )

    old = order.owned_product
    if old is None:
        return JsonResponse(
            {'ok': False,
             'error': 'This manual product has no recorded stock-pool link, so a '
                      'matching replacement cannot be selected automatically.'},
            status=409,
        )

    # 2. Resolve the pool the replaced unit belongs to (the "kind"). The pool
    #    carries game+variant+credential_spec, so same-pool == same product kind.
    old_item = (
        OfferPoolItem.objects
        .filter(owned_product_id=old.pk)
        .order_by('-id')
        .first()
    )
    if old_item is None:
        return JsonResponse(
            {'ok': False,
             'error': 'This account is not linked to a stock pool, so a matching '
                      'replacement cannot be selected automatically.'},
            status=409,
        )

    # 3. Claim ONE unallocated item atomically. skip_locked => simultaneous
    #    clicks take DIFFERENT units, never the same one.
    item = (
        OfferPoolItem.objects
        .select_for_update(skip_locked=True)
        .filter(
            pool_id=old_item.pool_id,
            status=OfferPoolItemStatus.PENDING,
            pool_offer__isnull=True,      # unallocated
            reservation__isnull=True,     # not reserved by a dispatch
        )
        .exclude(owned_product_id=old.pk)
        .exclude(error_message__gt='')    # skip units with a known failure
        .select_related('owned_product')
        .order_by('id')                   # FIFO — rotate stock
        .first()
    )
    if item is None:
        return JsonResponse(
            {'ok': False, 'error': 'No unallocated pool stock available for this product.'},
            status=409,
        )

    new = item.owned_product

    # 4. Take the pool item out of the pool so the dispatcher can never pick it
    #    up later. It is unallocated (no pool_offer), and the schema's
    #    ``assigned_pool_item_has_offer`` constraint forbids CONSUMED without a
    #    pool_offer, so REMOVED is the correct terminal state here — equally
    #    un-dispatchable (the dispatcher only claims PENDING items).
    item.status = OfferPoolItemStatus.REMOVED
    item.consumed_at = timezone.now()
    item.save(update_fields=['status', 'consumed_at', 'updated_at'])

    # 5. Retire the old unit, swap it on the order.
    old.status = OwnedProductStatus.REPLACED
    old.save(update_fields=['status', 'updated_at'])
    order.owned_product = new
    order.save(update_fields=['owned_product', 'updated_at'])

    # 5b. Send the replaced (faulty) account's pool item to a terminal state so
    #     it can never be re-offered as a replacement or counted as stock (both
    #     paths only consider PENDING items). It surfaces in the pool's Faulty
    #     section via the OrderReplacement record below.
    if old_item.status != OfferPoolItemStatus.REMOVED:
        old_item.status = OfferPoolItemStatus.REMOVED
        old_item.error_message = f'Replaced (faulty): {reason}'
        old_item.save(update_fields=['status', 'error_message', 'updated_at'])

    # 6. Audit — reason + typed name + the actual logged-in user.
    OrderReplacement.objects.create(
        order=order, old_product=old, new_product=new,
        pool_item=item, reason=reason,
        employee_name=employee_name, created_by=request.user,
    )
    logger.info(
        "Order %s replaced: owned_product %s -> %s (pool_item %s, by %s)",
        order.pk, old.pk, new.pk, item.pk, request.user,
    )

    return JsonResponse({'ok': True, 'credentials': {
        'login': new.login,
        'password': new.password,
        'email': new.email,
        'email_password': new.email_password,
        'ref_key': new.ref_key,
    }})
