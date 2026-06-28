import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from django.utils import timezone

from apps.inventory.enums import DropshipProductStatus, OwnedProductStatus
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
    if they have no other active listings. Preserve pool audit state."""
    if instance.status not in (ListingStatus.CLOSED, ListingStatus.DELETED):
        return

    from apps.posting.models import (
        OfferPoolActiveOffer,
        OfferPoolActiveOfferStatus,
        PoolOffer,
        PoolOfferStatus,
    )

    # A local listing lifecycle event must never cascade-delete the independent
    # stock pool. Relist/recovery can attach a replacement listing later.
    affected = PoolOffer.objects.filter(listing=instance).update(
        status=PoolOfferStatus.ERROR,
        last_error=f'Listing status changed to {instance.status}',
    )
    if affected:
        logger.info(
            "Marked %d PoolOffer(s) ERROR for Listing #%d (status → %s)",
            affected, instance.pk, instance.status,
        )

    OfferPoolActiveOffer.objects.filter(
        listing=instance,
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).update(status=OfferPoolActiveOfferStatus.DELISTED)

    # ── Dropship cascade ──────────────────────────────────────────────
    # If this listing was tied to a DropshipProduct, mark it DELETED
    # when no other LISTED listing remains for that DP.
    _cascade_dropship_product(instance)

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


# ---------------------------------------------------------------------------
# Helper: cascade listing deactivation to DropshipProduct
# ---------------------------------------------------------------------------
def _cascade_dropship_product(listing: Listing) -> None:
    """Mark the linked DropshipProduct as DELETED when no LISTED listing remains."""
    dp = listing.dropship_product
    if dp is None or dp.status != DropshipProductStatus.LISTED:
        return

    has_other_listed = Listing.objects.filter(
        dropship_product=dp,
        status=ListingStatus.LISTED,
    ).exclude(pk=listing.pk).exists()

    if not has_other_listed:
        dp.status = DropshipProductStatus.DELETED
        dp.deleted_at = timezone.now()
        dp.save(update_fields=['status', 'deleted_at', 'updated_at'])
        logger.info(
            "DropshipProduct #%d -> deleted (Listing #%d deactivated, no other active)",
            dp.pk, listing.pk,
        )
