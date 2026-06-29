"""RobuxCrate API endpoints — lookup, create-order, refresh, list, batch-status, config."""
from __future__ import annotations

import logging
import uuid

from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from apps.integrations.models import (
    IntegrationAccount,
    IntegrationCredential,
    ServiceCredential,
)
from apps.integrations.services.roblox import RobloxService
from apps.tools.helpers import (
    api_role_required,
    create_lookup_token,
    parse_json_body,
    verify_lookup_token,
)
from apps.tools.models import RobuxCrateBatch, RobuxCrateOrder
from apps.tools.services.robuxcrate import cancel_order, refresh_order_status

logger = logging.getLogger(__name__)

# ── Validation constants ──────────────────────────────────────────

_USERNAME_MAX = 50
_PLACE_NAME_MAX = 200
_QUANTITY_MIN, _QUANTITY_MAX = 1, 20
_ROBUX_MIN, _ROBUX_MAX = 1, 1_000_000
# Auto-place: cap how many candidate places we will sequentially try, to bound
# the number of attempts (sellers realistically have a handful of public games).
_AUTO_PLACE_MAX_CANDIDATES = 10


def _get_roblox_client():
    """Build a RobloxFacade from the first active roblox ServiceCredential."""
    cred = ServiceCredential.objects.filter(service_type='roblox', is_active=True).first()
    if cred is None:
        return None
    return RobloxService.build_client(cred)


# ── 1) Lookup Roblox user → places + signed token ────────────────

@api_role_required('admin', 'user')
@require_POST
def lookup_roblox_user(request):
    """Username → userId → public places list + signed lookup token."""
    body, err = parse_json_body(request)
    if err:
        return err

    username = (body.get('username') or '').strip()
    if not username or len(username) > _USERNAME_MAX:
        return JsonResponse({'error': 'Invalid username'}, status=400)

    client = _get_roblox_client()
    if not client:
        return JsonResponse(
            {'error': 'Roblox service not configured — add an active credential with service type "roblox"'},
            status=503,
        )

    result = client.lookup_user_with_places(username)

    if not result.ok:
        error = result.error
        status_code = 502
        if error:
            if error.category.value == 'not_found':
                status_code = 404
            elif error.category.value == 'rate_limit':
                status_code = 429
        message = error.message if error else 'Roblox API error'
        return JsonResponse({'error': message}, status=status_code)

    lookup = result.data
    user = lookup.user
    places = [{'place_id': p.place_id, 'name': p.name} for p in lookup.places]
    place_ids = [p.place_id for p in lookup.places]

    lookup_token = create_lookup_token(user.user_id, user.username, place_ids)

    response = {
        'ok': True,
        'user_id': user.user_id,
        'username': user.username,
        'display_name': user.display_name,
        'places': places,
        'lookup_token': lookup_token,
    }
    if lookup.partial:
        response['warning'] = 'Not all games could be loaded — some may be missing'
        response['partial'] = True

    return JsonResponse(response)


# ── 2) Create order batch ─────────────────────────────────────────

@api_role_required('admin', 'user')
@require_POST
def create_order(request):
    """Create a batch of N RobuxCrate gamepass orders (processed in background)."""
    body, err = parse_json_body(request)
    if err:
        return err

    # -- Validate lookup token --
    lookup_token = body.get('lookup_token', '')
    if not lookup_token:
        return JsonResponse({'error': 'lookup_token is required — perform username lookup first'}, status=400)

    token_data = verify_lookup_token(lookup_token)
    if not token_data:
        return JsonResponse({'error': 'Lookup token expired or invalid — please search username again'}, status=400)

    # -- Validate client_request_id (idempotency) --
    raw_crid = body.get('client_request_id', '')
    try:
        client_request_id = uuid.UUID(str(raw_crid))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': 'client_request_id must be a valid UUID'}, status=400)

    # -- Validate marketplace --
    marketplace = (body.get('marketplace') or '').strip()
    if marketplace not in RobuxCrateBatch.Marketplace.values:
        return JsonResponse(
            {'error': f'marketplace must be one of: {", ".join(RobuxCrateBatch.Marketplace.values)}'},
            status=400,
        )

    # -- Validate marketplace_order_id --
    marketplace_order_id = (body.get('marketplace_order_id') or '').strip()
    if not marketplace_order_id:
        return JsonResponse({'error': 'marketplace_order_id is required'}, status=400)

    # -- Validate marketplace_store --
    try:
        store_id = int(body.get('marketplace_store_id', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'marketplace_store_id must be an integer'}, status=400)
    if store_id <= 0:
        return JsonResponse({'error': 'marketplace_store_id is required'}, status=400)

    try:
        store_cred = IntegrationCredential.objects.select_related('account').get(
            id=store_id, is_active=True,
        )
    except IntegrationCredential.DoesNotExist:
        return JsonResponse({'error': 'Marketplace store not found or inactive'}, status=400)

    # -- Validate merchant --
    try:
        merchant_id = int(body.get('merchant_id', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'merchant_id must be an integer'}, status=400)
    if merchant_id <= 0:
        return JsonResponse({'error': 'merchant_id is required'}, status=400)

    try:
        merchant = ServiceCredential.objects.get(
            id=merchant_id, service_type='robuxcrate', is_active=True,
        )
    except ServiceCredential.DoesNotExist:
        return JsonResponse({'error': 'RbxCrate merchant not found or inactive'}, status=400)

    # -- Place selection: manual single place OR auto-place (try all) --
    auto_place = bool(body.get('auto_place', False))
    token_place_ids = token_data.get('pids', [])
    # Names are cosmetic; map any client-supplied place names onto verified IDs.
    sent_places = body.get('places') or []
    name_map: dict[int, str] = {}
    if isinstance(sent_places, list):
        for p in sent_places:
            try:
                name_map[int(p['place_id'])] = str(p.get('name') or '')[:_PLACE_NAME_MAX]
            except (KeyError, ValueError, TypeError):
                continue

    if auto_place:
        # Candidates = every place the user owns (verified via token), in order.
        if not token_place_ids:
            return JsonResponse(
                {'error': 'Auto-place requires at least one place for the user'},
                status=400,
            )
        candidate_ids = token_place_ids[:_AUTO_PLACE_MAX_CANDIDATES]
        place_candidates = [
            {'place_id': pid, 'name': name_map.get(pid, '')}
            for pid in candidate_ids
        ]
        place_id = place_candidates[0]['place_id']
        place_name = place_candidates[0]['name']
    else:
        # Manual: a single place_id, validated against the token.
        try:
            place_id = int(body.get('place_id', 0))
        except (ValueError, TypeError):
            return JsonResponse({'error': 'place_id must be a positive integer'}, status=400)

        if place_id <= 0:
            return JsonResponse({'error': 'place_id must be a positive integer'}, status=400)

        if place_id not in token_place_ids:
            return JsonResponse(
                {'error': 'Selected place_id does not belong to the looked-up user'},
                status=400,
            )
        place_name = name_map.get(place_id, '')
        place_candidates = [{'place_id': place_id, 'name': place_name}]

    # -- Validate robux_amount --
    try:
        robux_amount = int(body.get('robux_amount', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'robux_amount must be a positive integer'}, status=400)

    if not (_ROBUX_MIN <= robux_amount <= _ROBUX_MAX):
        return JsonResponse(
            {'error': f'robux_amount must be between {_ROBUX_MIN} and {_ROBUX_MAX:,}'},
            status=400,
        )

    # -- Validate quantity --
    try:
        quantity = int(body.get('quantity', 1))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'quantity must be an integer'}, status=400)

    if not (_QUANTITY_MIN <= quantity <= _QUANTITY_MAX):
        return JsonResponse(
            {'error': f'quantity must be between {_QUANTITY_MIN} and {_QUANTITY_MAX}'},
            status=400,
        )

    # -- Extract verified data from token --
    roblox_user_id = token_data['uid']
    roblox_username = token_data['un']

    # -- Idempotency check --
    try:
        existing = RobuxCrateBatch.objects.get(client_request_id=client_request_id)
    except RobuxCrateBatch.DoesNotExist:
        existing = None

    if existing:
        return _batch_response(existing)

    # -- Create batch + orders atomically --
    try:
        with transaction.atomic():
            batch = RobuxCrateBatch.objects.create(
                client_request_id=client_request_id,
                created_by=request.user,
                marketplace=marketplace,
                marketplace_order_id=marketplace_order_id,
                marketplace_store=store_cred,
                merchant=merchant,
                roblox_username=roblox_username,
                roblox_user_id=roblox_user_id,
                place_id=place_id,
                place_name=place_name,
                auto_place=auto_place,
                place_candidates=place_candidates,
                place_attempt_index=0,
                robux_amount=robux_amount,
                quantity=quantity,
            )
            RobuxCrateOrder.objects.bulk_create([
                RobuxCrateOrder(
                    batch=batch,
                    created_by=request.user,
                )
                for _ in range(quantity)
            ])
    except IntegrityError:
        existing = RobuxCrateBatch.objects.get(client_request_id=client_request_id)
        return _batch_response(existing)

    return _batch_response(batch, status_code=201)


def _batch_response(batch: RobuxCrateBatch, status_code: int = 200) -> JsonResponse:
    """Serialize a batch with its order summaries."""
    orders = batch.orders.all()
    statuses = [o.status for o in orders]

    return JsonResponse({
        'ok': True,
        'batch_id': str(batch.id),
        'client_request_id': str(batch.client_request_id),
        'marketplace': batch.marketplace,
        'marketplace_order_id': batch.marketplace_order_id,
        'roblox_username': batch.roblox_username,
        'place_id': batch.place_id,
        'place_name': batch.place_name,
        'auto_place': batch.auto_place,
        'place_attempt_index': batch.place_attempt_index,
        'place_count': len(batch.place_candidates or []),
        'robux_amount': batch.robux_amount,
        'quantity': batch.quantity,
        'batch_status': batch.status,
        'delivery_error': batch.delivery_error,
        'created_count': len(statuses),
        'successful_count': sum(1 for s in statuses if s == RobuxCrateOrder.Status.COMPLETED),
        'failed_count': sum(1 for s in statuses if s in {RobuxCrateOrder.Status.ERROR, RobuxCrateOrder.Status.CANCELLED}),
        'pending_count': sum(1 for s in statuses if s in {
            RobuxCrateOrder.Status.PENDING, RobuxCrateOrder.Status.QUEUED,
            RobuxCrateOrder.Status.UNKNOWN,
        }),
        'orders': [
            {
                'id': str(o.id),
                'status': o.status,
                'error_message': o.error_message,
            }
            for o in orders
        ],
    }, status=status_code)


# ── 3) Batch status (polling endpoint) ────────────────────────────

@api_role_required('admin', 'user')
@require_GET
def batch_status(request, batch_id):
    """Poll batch processing progress."""
    try:
        batch = RobuxCrateBatch.objects.get(id=batch_id)
    except RobuxCrateBatch.DoesNotExist:
        return JsonResponse({'error': 'Batch not found'}, status=404)

    if not request.user.is_superuser and request.user.role != 'admin':
        if batch.created_by_id != request.user.id:
            return JsonResponse({'error': 'Permission denied'}, status=403)

    return _batch_response(batch)


# ── 4) Refresh single order status ────────────────────────────────

@api_role_required('admin', 'user')
@require_POST
def refresh_order_status_view(request, order_id):
    """Refresh a single order's status from RbxCrate API."""
    try:
        order = RobuxCrateOrder.objects.select_related('batch').get(id=order_id)
    except RobuxCrateOrder.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

    if not request.user.is_superuser and request.user.role != 'admin':
        if order.created_by_id != request.user.id:
            return JsonResponse({'error': 'Permission denied'}, status=403)

    ok, error_msg = refresh_order_status(order)
    order.refresh_from_db()

    return JsonResponse({
        'ok': ok,
        'order_id': str(order.id),
        'status': order.status,
        'error_message': order.error_message,
        'error': error_msg,
    })


# ── 4b) Cancel single order ────────────────────────────────────────

@api_role_required('admin', 'user')
@require_POST
def cancel_order_view(request, order_id):
    """Cancel a single order via RbxCrate API."""
    try:
        order = RobuxCrateOrder.objects.select_related('batch__merchant').get(id=order_id)
    except RobuxCrateOrder.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

    if not request.user.is_superuser and request.user.role != 'admin':
        if order.created_by_id != request.user.id:
            return JsonResponse({'error': 'Permission denied'}, status=403)

    ok, error_msg = cancel_order(order)
    if not ok:
        return JsonResponse({'ok': False, 'error': error_msg}, status=400)

    return JsonResponse({
        'ok': True,
        'order_id': str(order.id),
        'status': order.status,
    })


# ── 5) List orders (paginated, filtered, scoped) ─────────────────

@api_role_required('admin', 'user')
@require_GET
def list_orders(request):
    """Paginated order list with optional filters."""
    qs = (
        RobuxCrateOrder.objects
        .select_related('batch', 'batch__marketplace_store__account', 'created_by')
        .order_by('-created_at')
    )

    if not request.user.is_superuser and request.user.role != 'admin':
        qs = qs.filter(created_by=request.user)

    status_filter = request.GET.get('status', '').strip()
    if status_filter and status_filter in RobuxCrateOrder.Status.values:
        qs = qs.filter(status=status_filter)

    q = request.GET.get('q', '').strip()
    if q:
        text_q = (
            Q(batch__roblox_username__icontains=q)
            | Q(batch__marketplace_order_id__icontains=q)
            | Q(batch__place_id__icontains=q)
        )
        try:
            order_uuid = uuid.UUID(q)
            text_q = text_q | Q(id=order_uuid)
        except ValueError:
            pass
        qs = qs.filter(text_q)

    try:
        per_page = min(100, max(1, int(request.GET.get('per_page', 50))))
    except (ValueError, TypeError):
        per_page = 50

    try:
        page_num = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page_num = 1

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(page_num)

    orders = []
    for o in page:
        store = o.batch.marketplace_store
        orders.append({
            'id': str(o.id),
            'batch_id': str(o.batch_id),
            'marketplace': o.batch.marketplace,
            'marketplace_order_id': o.batch.marketplace_order_id,
            'store_name': store.account.name if store and store.account else None,
            'roblox_username': o.batch.roblox_username,
            'roblox_user_id': o.batch.roblox_user_id,
            'place_id': o.batch.place_id,
            'place_name': o.batch.place_name,
            'robux_amount': o.batch.robux_amount,
            'status': o.status,
            'error_message': o.error_message,
            'batch_status': o.batch.status,
            'delivery_error': o.batch.delivery_error,
            'created_by': o.created_by.username if o.created_by else None,
            'created_at': o.created_at.isoformat(),
            'updated_at': o.updated_at.isoformat(),
        })

    return JsonResponse({
        'ok': True,
        'orders': orders,
        'page': page.number,
        'total_pages': paginator.num_pages,
        'total_count': paginator.count,
    })


# ── 6) Config endpoints (marketplace stores + merchants) ─────────

@api_role_required('admin', 'user')
@require_GET
def list_marketplace_stores(request):
    """Return active marketplace stores for dropdown selection."""
    marketplace = request.GET.get('marketplace', '').strip()

    qs = IntegrationCredential.objects.filter(
        is_active=True,
    ).select_related('account')

    if marketplace:
        qs = qs.filter(account__provider=marketplace)

    stores = [
        {
            'id': cred.id,
            'name': cred.account.name,
            'provider': cred.account.provider,
            'slug': cred.account.slug,
        }
        for cred in qs
    ]

    return JsonResponse({'ok': True, 'stores': stores})


@api_role_required('admin', 'user')
@require_GET
def list_merchants(request):
    """Return active RbxCrate merchants for dropdown selection."""
    merchants = [
        {
            'id': cred.id,
            'name': cred.name,
            'slug': cred.slug,
        }
        for cred in ServiceCredential.objects.filter(
            service_type='robuxcrate', is_active=True,
        )
    ]

    return JsonResponse({'ok': True, 'merchants': merchants})
