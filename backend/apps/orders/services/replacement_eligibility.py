from apps.posting.models import OfferPoolItem
from apps.orders.enums import OrderStatus


REPLACEABLE_SOLD_STATUSES = {
    OrderStatus.DELIVERED,
    OrderStatus.COMPLETED,
    OrderStatus.DISPUTED,
    OrderStatus.DISPUTE_RESOLVED,
}


def is_replaceable_manual_order(order, *, has_pool_item=None):
    """Return whether an order may enter the guarded manual replacement flow.

    This predicate controls visibility only. The replacement endpoint repeats all
    safety checks while holding its allocation transaction.
    """
    if not (
        order
        and not getattr(order, 'is_instant', False)
        and not getattr(order, 'dropship_product_id', None)
        and getattr(order, 'owned_product_id', None)
        and getattr(order, 'status', None) in REPLACEABLE_SOLD_STATUSES
    ):
        return False
    if has_pool_item is None:
        return OfferPoolItem.objects.filter(
            owned_product_id=order.owned_product_id,
        ).exists()
    return bool(has_pool_item)


def replacement_visibility(order, *, has_pool_item=None, already_replaced=False):
    """Return a stable UI state for every row in a pool's sold ledger."""
    if order is None:
        return "waiting_order", "Await order", "Waiting for a verified marketplace order sync."
    if already_replaced:
        return "already_replaced", "Replaced", "A replacement has already been assigned for this order."
    if getattr(order, "is_instant", False):
        return "instant", "Instant order", "Instant orders cannot use manual pool replacement."
    if getattr(order, "dropship_product_id", None):
        return "dropship", "Dropship", "Dropship orders cannot use manual pool replacement."
    if not getattr(order, "owned_product_id", None):
        return "no_owned_product", "No owned key", "This order has no self-owned account linked."
    if getattr(order, "status", None) not in REPLACEABLE_SOLD_STATUSES:
        return "not_confirmed", "Not confirmed", "Replacement is available only after a confirmed sale status."
    if has_pool_item is False:
        return "no_pool_link", "No pool key", "This order is not linked to a pool account."
    return "eligible", "Replace", "Allocate a compatible replacement account."
