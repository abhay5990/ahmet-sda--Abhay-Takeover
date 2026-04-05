from django.db import models

from core.enums import ProductCategory
from .enums import OrderStatus


class Order(models.Model):
    is_instant = models.BooleanField(
        default=True,
        help_text='True=instant delivery, False=manual/dropship',
    )
    product_category = models.CharField(
        max_length=20,
        choices=ProductCategory.choices,
        default=ProductCategory.ACCOUNTS,
    )
    owned_product = models.ForeignKey(
        'inventory.OwnedProduct',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
        help_text='Instant: set on creation. Manual: set after fulfillment',
    )
    dropship_product = models.ForeignKey(
        'inventory.DropshipProduct',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )
    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )
    store_order_id = models.CharField(
        max_length=255,
        help_text='Order ID on the platform',
    )
    store_listing_id = models.CharField(
        max_length=255, blank=True,
        help_text='Listing ID on the platform (for cross-referencing)',
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    our_fee = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text='Platform commission/fee',
    )
    sold_at = models.DateTimeField(null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'store_order_id'],
                name='unique_account_order',
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['store_order_id']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['-sold_at']),
            models.Index(fields=['integration_account', '-created_at']),
        ]

    def __str__(self):
        return f"Order {self.store_order_id} ({self.get_status_display()})"
