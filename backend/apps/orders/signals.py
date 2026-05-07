import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.inventory.enums import DropshipProductStatus, OwnedProductStatus
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from .enums import OrderStatus
from .models import Order

logger = logging.getLogger(__name__)

CANCEL_STATUSES = (OrderStatus.CANCELLED, OrderStatus.REFUNDED)


# ---------------------------------------------------------------------------
# Order created/status changed -> OwnedProduct lifecycle
# ---------------------------------------------------------------------------
@receiver(post_save, sender=Order)
def order_status_changed(sender, instance, created, **kwargs):
    """Handle OwnedProduct status transitions based on Order lifecycle.

    Rules (from ADR-006):
      - Order created (pending/delivered) -> OwnedProduct: listed -> sold
      - Second+ order on same product    -> OwnedProduct: sold -> multiple_sold
      - Order cancelled/refunded (no other active orders) -> revert status
    """
    order = instance

    if order.status in CANCEL_STATUSES:
        _handle_order_cancelled(order)
    elif order.status in (OrderStatus.PENDING, OrderStatus.DELIVERED, OrderStatus.COMPLETED):
        _handle_order_sold(order, created)


def _handle_order_sold(order, created):
    """Mark OwnedProduct/DropshipProduct as sold, close listing."""
    owned = order.owned_product

    # --- Owned product path (instant delivery) ---
    if owned:
        active_order_count = Order.objects.filter(
            owned_product=owned,
        ).exclude(
            status__in=CANCEL_STATUSES,
        ).count()

        if active_order_count > 1 and owned.status != OwnedProductStatus.MULTIPLE_SOLD:
            owned.status = OwnedProductStatus.MULTIPLE_SOLD
            owned.save(update_fields=['status', 'updated_at'])
            logger.warning(
                "OwnedProduct #%d -> multiple_sold (%d active orders)",
                owned.pk, active_order_count,
            )
        elif active_order_count == 1 and owned.status == OwnedProductStatus.LISTED:
            owned.status = OwnedProductStatus.SOLD
            owned.save(update_fields=['status', 'updated_at'])
            logger.info(
                "OwnedProduct #%d -> sold (Order #%d)", owned.pk, order.pk,
            )

    # --- Dropship product path ---
    dp = order.dropship_product
    if dp and dp.status != DropshipProductStatus.SOLD:
        dp.status = DropshipProductStatus.SOLD
        dp.save(update_fields=['status', 'updated_at'])
        logger.info(
            "DropshipProduct #%d -> sold (Order #%d)", dp.pk, order.pk,
        )

        # Mark any OwnedProduct purchased from this DP as sold
        # (product_origin FK links OP to the DP it was sourced from)
        _mark_origin_owned_products_sold(dp, order)

    # --- Close the listing that was sold through ---
    if order.listing and order.listing.status == ListingStatus.LISTED:
        order.listing.status = ListingStatus.CLOSED
        order.listing.save(update_fields=['status', 'updated_at'])
        logger.info(
            "Listing #%d -> closed (Order #%d)", order.listing.pk, order.pk,
        )

    # Unlink sold OwnedProduct from same-account listings (DB-only, no API call).
    # Marketplace already handles removal on its side when an order completes.
    if owned and created:
        _unlink_same_account_listings(order, owned)


def _handle_order_cancelled(order):
    """Revert OwnedProduct status when an order is cancelled/refunded.

    If no other active orders remain:
      - Has active listings -> listed
      - No active listings  -> draft
    """
    owned = order.owned_product
    if not owned:
        return

    if owned.status not in (
        OwnedProductStatus.SOLD,
        OwnedProductStatus.MULTIPLE_SOLD,
    ):
        return

    remaining = Order.objects.filter(
        owned_product=owned,
    ).exclude(
        status__in=CANCEL_STATUSES,
    ).exclude(pk=order.pk).count()

    if remaining > 1:
        # Still multiple active orders
        return
    elif remaining == 1:
        owned.status = OwnedProductStatus.SOLD
        owned.save(update_fields=['status', 'updated_at'])
        logger.info(
            "OwnedProduct #%d -> sold (order cancelled, %d remaining)",
            owned.pk, remaining,
        )
    else:
        # No active orders remain — check listings
        has_active_listing = ListingOwnedProduct.objects.filter(
            owned_product=owned,
            listing__status=ListingStatus.LISTED,
        ).exists()

        if has_active_listing:
            owned.status = OwnedProductStatus.LISTED
            owned.save(update_fields=['status', 'updated_at'])
            logger.info(
                "OwnedProduct #%d -> listed (order cancelled, active listings exist)",
                owned.pk,
            )
        else:
            owned.status = OwnedProductStatus.DRAFT
            owned.save(update_fields=['status', 'updated_at'])
            logger.info(
                "OwnedProduct #%d -> draft (order cancelled, no active listings)",
                owned.pk,
            )


# ---------------------------------------------------------------------------
# DropshipProduct → OwnedProduct cascade
# ---------------------------------------------------------------------------

def _mark_origin_owned_products_sold(dp, order):
    """Mark OwnedProducts sourced from this DropshipProduct as sold.

    When a DropshipProduct is sold, any OwnedProduct created from it
    (product_origin FK) should also reflect that it is no longer available.
    """
    from apps.inventory.models import OwnedProduct

    to_update = list(
        OwnedProduct.objects.filter(
            product_origin=dp,
            status=OwnedProductStatus.LISTED,
        )
    )
    if not to_update:
        return

    for op in to_update:
        op.status = OwnedProductStatus.SOLD

    OwnedProduct.objects.bulk_update(to_update, ['status', 'updated_at'])
    logger.info(
        "OwnedProduct(s) %s -> sold via DropshipProduct #%d (Order #%d)",
        [op.pk for op in to_update], dp.pk, order.pk,
    )


# ---------------------------------------------------------------------------
# Same-account listing cleanup (DB-only, no API call)
# ---------------------------------------------------------------------------
def _unlink_same_account_listings(order, owned):
    """Unlink sold OwnedProduct from same-account listings.

    When an order is created, the marketplace already removes the credential
    from the offer on its side. This function syncs our DB to match:
      - Remove ListingOwnedProduct link for the sold credential
      - If no other credentials remain on the listing -> mark CLOSED
      - If other credentials remain -> listing stays LISTED
    """
    same_account_lops = ListingOwnedProduct.objects.filter(
        owned_product=owned,
        listing__integration_account=order.integration_account,
        listing__status__in=(ListingStatus.LISTED, ListingStatus.PAUSED),
    ).select_related('listing')

    for lop in same_account_lops:
        listing = lop.listing

        # Count how many OwnedProducts are linked (before removing this one)
        total_linked = ListingOwnedProduct.objects.filter(listing=listing).count()

        # Unlink sold credential
        lop.delete()

        if total_linked <= 1:
            # This was the only credential -> listing is empty, close it
            listing.status = ListingStatus.CLOSED
            listing.save(update_fields=['status', 'updated_at'])
            logger.info(
                "Listing #%d -> closed (last credential sold, Order #%d)",
                listing.pk, order.pk,
            )
        else:
            logger.info(
                "Listing #%d: unlinked sold OwnedProduct #%d (%d remaining)",
                listing.pk, owned.pk, total_linked - 1,
            )
