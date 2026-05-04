import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from apps.inventory.enums import OwnedProductStatus
from .enums import ListingStatus
from .models import Listing, ListingOwnedProduct

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ListingOwnedProduct created -> OwnedProduct: draft -> listed
# ---------------------------------------------------------------------------
@receiver(post_save, sender=ListingOwnedProduct)
def owned_product_listed(sender, instance, created, **kwargs):
    """When an OwnedProduct is attached to a Listing, mark it as listed."""
    if not created:
        return

    owned = instance.owned_product
    listing = instance.listing

    if owned.status == OwnedProductStatus.DRAFT:
        owned.status = OwnedProductStatus.LISTED
        owned.save(update_fields=['status', 'updated_at'])
        logger.info(
            "OwnedProduct #%d -> listed (attached to Listing #%d on %s)",
            owned.pk, listing.pk, listing.integration_account,
        )


# ---------------------------------------------------------------------------
# ListingOwnedProduct deleted -> if no more listings, OwnedProduct: listed -> draft
# ---------------------------------------------------------------------------
@receiver(post_delete, sender=ListingOwnedProduct)
def owned_product_maybe_unlisted(sender, instance, **kwargs):
    """When an OwnedProduct is detached, revert to draft if no active listings remain."""
    try:
        owned = instance.owned_product
    except Exception:
        return  # OwnedProduct itself was deleted

    if owned.status != OwnedProductStatus.LISTED:
        return

    has_active = ListingOwnedProduct.objects.filter(
        owned_product=owned,
        listing__status=ListingStatus.LISTED,
    ).exists()

    if not has_active:
        owned.status = OwnedProductStatus.DRAFT
        owned.save(update_fields=['status', 'updated_at'])
        logger.info(
            "OwnedProduct #%d -> draft (no active listings remain)", owned.pk,
        )


# ---------------------------------------------------------------------------
# Listing status changed to closed/deleted -> check attached OwnedProducts
# ---------------------------------------------------------------------------
@receiver(post_save, sender=Listing)
def listing_deactivated(sender, instance, **kwargs):
    """When a Listing is closed/deleted, revert its OwnedProducts to draft
    if they have no other active listings. Also delete associated pools."""
    if instance.status not in (ListingStatus.CLOSED, ListingStatus.DELETED):
        return

    # Delete associated offer pools — offer no longer exists on marketplace
    from apps.posting.models import OfferPool

    deleted_pools = OfferPool.objects.filter(listing=instance).delete()
    if deleted_pools[0] > 0:
        logger.info(
            "Deleted %d pool(s) for Listing #%d (status → %s)",
            deleted_pools[0], instance.pk, instance.status,
        )

    owned_products = [
        lop.owned_product
        for lop in instance.listing_owned_products.select_related('owned_product').all()
    ]

    for owned in owned_products:
        if owned.status != OwnedProductStatus.LISTED:
            continue

        has_other_active = ListingOwnedProduct.objects.filter(
            owned_product=owned,
            listing__status=ListingStatus.LISTED,
        ).exclude(listing=instance).exists()

        if not has_other_active:
            owned.status = OwnedProductStatus.DRAFT
            owned.save(update_fields=['status', 'updated_at'])
            logger.info(
                "OwnedProduct #%d -> draft (Listing #%d deactivated, no other active)",
                owned.pk, instance.pk,
            )
