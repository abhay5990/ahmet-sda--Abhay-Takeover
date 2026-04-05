import logging

from django.utils import timezone

from apps.inventory.enums import OwnedProductStatus
from apps.listings.models import Listing
from apps.listings.enums import ListingStatus

logger = logging.getLogger(__name__)


class OrderSyncService:
    """Handles order synchronization and duplicate sale prevention."""

    @staticmethod
    def handle_product_sold(owned_product, sold_listing):
        """When a product is sold on one account, remove from all others."""
        owned_product.status = OwnedProductStatus.SOLD
        owned_product.save(update_fields=['status', 'updated_at'])

        sold_listing.status = ListingStatus.CLOSED
        sold_listing.removed_at = timezone.now()
        sold_listing.save(update_fields=['status', 'removed_at', 'updated_at'])

        other_listings = Listing.objects.filter(
            listing_owned_products__owned_product=owned_product,
            status=ListingStatus.LISTED,
        ).exclude(pk=sold_listing.pk)

        removed_count = 0
        for listing in other_listings:
            listing.status = ListingStatus.CLOSED
            listing.removed_at = timezone.now()
            listing.save(update_fields=['status', 'removed_at', 'updated_at'])
            removed_count += 1
            account_name = listing.integration_account.name if listing.integration_account else 'unknown'
            sold_account = sold_listing.integration_account.name if sold_listing.integration_account else 'unknown'
            logger.info(
                f"Removed listing {listing.store_listing_id} from {account_name} "
                f"(product sold on {sold_account})"
            )

        return removed_count
