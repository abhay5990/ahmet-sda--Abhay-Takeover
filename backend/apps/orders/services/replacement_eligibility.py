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
