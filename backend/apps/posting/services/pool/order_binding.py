"""Exact pool-item to confirmed marketplace-order binding helpers.

These helpers are deliberately fail-closed: they only bind an item when the
order already belongs to the same OwnedProduct, was placed through the exact
store that owns the pool lane, and has reached a confirmed sale status.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.posting.models import OfferPoolItemStatus, PoolSaleEvent
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.services.registry import build_service, get_service_class


CONFIRMED_SALE_STATUSES = {
    OrderStatus.DELIVERED,
    OrderStatus.COMPLETED,
    OrderStatus.DISPUTED,
}


@dataclass(frozen=True)
class OrderBindingResult:
    bound_item_ids: tuple[int, ...]
    skipped_item_ids: tuple[int, ...]
    sync_error: str = ''


def _closest_order(candidates, consumed_at):
    if consumed_at is None:
        return candidates[0]

    def distance(order):
        reference = order.sold_at or order.created_at
        return abs((reference - consumed_at).total_seconds()) if reference else float('inf')

    return min(candidates, key=distance)


def find_exact_confirmed_order(item, *, excluded_order_ids=frozenset()):
    """Return one safely attributable confirmed order or ``None``.

    The `OwnedProduct` relation is the account-identity proof.  The exact
    lane store prevents an account sold elsewhere from consuming this lane.
    """
    if not item.owned_product_id or not item.pool_offer_id:
        return None

    listing = getattr(item.pool_offer, 'listing', None)
    integration_account_id = getattr(listing, 'integration_account_id', None)
    if not integration_account_id:
        return None

    candidates = list(
        Order.objects.filter(
            owned_product_id=item.owned_product_id,
            integration_account_id=integration_account_id,
            status__in=CONFIRMED_SALE_STATUSES,
        ).exclude(pk__in=excluded_order_ids).order_by('-sold_at', '-created_at')
    )
    return _closest_order(candidates, item.consumed_at) if candidates else None


def bind_consumed_items_to_confirmed_orders(items) -> OrderBindingResult:
    """Create exact processed sale events for a batch of consumed pool items.

    The operation is idempotent and never changes an item when the remote
    disappearance cannot be proven to be a sale by a matching confirmed order.
    """
    bound_ids: list[int] = []
    skipped_ids: list[int] = []
    bound_order_ids = set(
        PoolSaleEvent.objects.filter(order_id__isnull=False).values_list('order_id', flat=True)
    )

    with transaction.atomic():
        for item in items:
            if item.status != OfferPoolItemStatus.CONSUMED:
                skipped_ids.append(item.pk)
                continue
            existing = PoolSaleEvent.objects.filter(pool_item_id=item.pk).first()
            if existing and existing.order_id:
                skipped_ids.append(item.pk)
                continue
            order = find_exact_confirmed_order(item, excluded_order_ids=bound_order_ids)
            if order is None:
                skipped_ids.append(item.pk)
                continue

            PoolSaleEvent.objects.get_or_create(
                event_key=f'first-pass-order-binding:item:{item.pk}:order:{order.pk}',
                defaults={
                    'listing': order.listing or item.pool_offer.listing,
                    'pool_offer': item.pool_offer,
                    'pool_item': item,
                    'order_id': order.pk,
                    'outcome': 'processed',
                    'processed_at': timezone.now(),
                },
            )
            fields = []
            if item.remote_state != 'sold':
                item.remote_state = 'sold'
                fields.append('remote_state')
            if item.consumed_at is None:
                item.consumed_at = order.sold_at or timezone.now()
                fields.append('consumed_at')
            if fields:
                fields.append('updated_at')
                item.save(update_fields=fields)
            bound_order_ids.add(order.pk)
            bound_ids.append(item.pk)

    return OrderBindingResult(tuple(bound_ids), tuple(skipped_ids))


def refresh_and_bind_consumed_items(items) -> OrderBindingResult:
    """Refresh one lane's order feed once, then bind exact confirmed orders.

    This runs only after the remote-count checker has *proven* a credential
    absent.  A refresh failure is intentionally non-destructive: items stay
    consumed/absent and no order is guessed or reused.
    """
    item_list = list(items)
    if not item_list:
        return OrderBindingResult((), ())
    pool_offer = item_list[0].pool_offer
    listing = getattr(pool_offer, 'listing', None)
    account = getattr(listing, 'integration_account', None)
    credential = getattr(account, 'credential', None)
    if not account or not credential or not credential.is_active:
        return OrderBindingResult((), tuple(item.pk for item in item_list), 'missing active store credentials')

    service_class = get_service_class(ResourceType.ORDERS, account.provider)
    if service_class is None:
        return OrderBindingResult((), tuple(item.pk for item in item_list), f'no order sync service for {account.provider}')

    try:
        proxy_pool = build_proxy_pool()
        service = build_service(
            ResourceType.ORDERS,
            account.provider,
            credential=credential,
            proxy_pool=proxy_pool,
            proxy_group=get_group_name(account),
        )
        service.run(account, mode=SyncMode.INCREMENTAL)
    except Exception as exc:  # Fail closed; caller records sanitized diagnostic.
        return OrderBindingResult(
            (), tuple(item.pk for item in item_list), f'{type(exc).__name__}: {exc}',
        )

    return bind_consumed_items_to_confirmed_orders(item_list)
