from django.db import models

from apps.integrations.models import Provider
from core.enums import ProductCategory
from .enums import FeeType, OrderStatus


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


class FeeRule(models.Model):
    """Marketplace fee rules.

    Lookup priority (most specific wins):
      1. marketplace + game + product_category + fee_type
      2. marketplace + game + fee_type
      3. marketplace + product_category + fee_type
      4. marketplace + fee_type  (default)

    Time-based versioning: effective_from/until allows the same rule
    to carry different rates across periods. The correct version is
    selected based on Order.sold_at date.
    """
    marketplace = models.CharField(
        max_length=20,
        choices=Provider.choices,
    )
    product_category = models.CharField(
        max_length=20,
        choices=ProductCategory.choices,
        blank=True,
        help_text='Empty = default for all categories',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='fee_rules',
        help_text='Empty = default for all games',
    )
    fee_type = models.CharField(
        max_length=10,
        choices=FeeType.choices,
        default=FeeType.SALE,
    )
    fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='Percentage rate (e.g. 10.00 = 10%)',
    )
    flat_fee = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=0,
        help_text='Fixed amount per order (e.g. completion fee €0.99)',
    )
    flat_fee_currency = models.CharField(
        max_length=3, default='EUR',
        help_text='Currency for the flat fee amount',
    )
    effective_from = models.DateField(
        help_text='Start date when this rule becomes effective',
    )
    effective_until = models.DateField(
        null=True, blank=True,
        help_text='Empty = still active',
    )
    note = models.TextField(
        blank=True,
        help_text='Description (e.g. source URL, reason for change)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fee_rules'
        ordering = ['marketplace', 'fee_type', '-effective_from']
        indexes = [
            models.Index(
                fields=['marketplace', 'fee_type', 'effective_from'],
                name='fee_rule_lookup_idx',
            ),
        ]

    def __str__(self):
        parts = [self.get_marketplace_display(), self.get_fee_type_display()]
        if self.product_category:
            parts.append(self.get_product_category_display())
        if self.game:
            parts.append(self.game.name)
        parts.append(f'{self.fee_percent}%')
        if self.flat_fee:
            parts.append(f'+{self.flat_fee} {self.flat_fee_currency}')
        return ' | '.join(parts)
