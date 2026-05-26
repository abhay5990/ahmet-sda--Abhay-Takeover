from django.db import models

from core.enums import ProductCategory
from .enums import ListingStatus


class Listing(models.Model):
    is_instant = models.BooleanField(
        default=True,
        help_text='True=OwnedProduct (instant), False=DropshipProduct (manual)',
    )
    dropship_product = models.ForeignKey(
        'inventory.DropshipProduct',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='listings',
        help_text='Dropship flow (null if instant)',
    )
    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='listings',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='listings',
    )
    store_listing_id = models.CharField(
        max_length=255,
        help_text='Listing ID on the platform (UUID for Eldorado, numeric for others)',
    )
    product_category = models.CharField(
        max_length=20,
        choices=ProductCategory.choices,
        default=ProductCategory.ACCOUNTS,
    )
    variant = models.CharField(
        max_length=64, blank=True,
        help_text='Canonical variant slug: pc, psn, xbox, na, euw, etc.',
    )
    status = models.CharField(
        max_length=20,
        choices=ListingStatus.choices,
        default=ListingStatus.LISTED,
    )
    title = models.CharField(max_length=500, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')

    listed_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'listings'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'store_listing_id'],
                name='unique_account_listing',
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['store_listing_id']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['integration_account', '-created_at']),
            models.Index(
                fields=['integration_account', 'game', 'status', 'variant'],
                name='listing_acct_game_status_var',
            ),
        ]

    def __str__(self):
        return f"{self.title or self.store_listing_id} ({self.get_status_display()})"


class ListingOwnedProduct(models.Model):
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='listing_owned_products',
    )
    owned_product = models.ForeignKey(
        'inventory.OwnedProduct',
        on_delete=models.CASCADE,
        related_name='listing_owned_products',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'listing_owned_products'
        constraints = [
            models.UniqueConstraint(
                fields=['listing', 'owned_product'],
                name='unique_listing_owned_product',
            ),
        ]

    def __str__(self):
        return f"Listing #{self.listing_id} - OwnedProduct #{self.owned_product_id}"
