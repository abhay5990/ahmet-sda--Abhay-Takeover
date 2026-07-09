import hashlib

from django.db import models

from core.encryption import EncryptedTextField
from .enums import OwnedProductStatus, DropshipProductStatus


class Category(models.Model):
    category_id = models.IntegerField(
        unique=True, null=True, blank=True,
        help_text='External category ID (e.g. LZT category_id)',
    )
    name = models.CharField(max_length=50, unique=True, help_text='Slug: steam, supercell, riot')
    title = models.CharField(max_length=100, help_text='Display: Steam, Supercell, Riot Games')
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'categories'
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.title


class Game(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True)
    acronym = models.CharField(max_length=20, null=True, blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='games',
    )
    icon = models.ImageField(upload_to='games/icons/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'games'
        ordering = ['name']

    def __str__(self):
        return self.name


class GamePlatformMapping(models.Model):
    PLATFORM_CHOICES = [
        ('eldorado', 'Eldorado'),
        ('gameboost', 'GameBoost'),
        ('playerauctions', 'PlayerAuctions'),
    ]

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name='platform_mappings',
    )
    platform = models.CharField(max_length=30, choices=PLATFORM_CHOICES)
    external_id = models.CharField(max_length=100)
    external_name = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'game_platform_mappings'
        unique_together = [('platform', 'external_id')]
        ordering = ['game', 'platform']

    def __str__(self):
        return f"{self.game.name} → {self.platform}:{self.external_id}"


class OwnedProduct(models.Model):
    # Account credentials
    login = models.CharField(max_length=255)
    password = EncryptedTextField()
    password_hash = models.CharField(
        max_length=64,
        help_text='SHA256 hash (informational, no longer part of unique key)',
    )
    email = models.CharField(max_length=255, blank=True)
    email_password = EncryptedTextField(blank=True)
    email_login_link = models.CharField(max_length=500, blank=True)
    security_email = models.CharField(max_length=255, blank=True)
    security_email_password = EncryptedTextField(blank=True)
    security_email_login_link = models.CharField(max_length=500, blank=True)

    # Classification
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='owned_products',
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='owned_products',
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=OwnedProductStatus.choices,
        default=OwnedProductStatus.DRAFT,
    )

    # Source tracking
    source_product_id = models.CharField(
        max_length=128, null=True, blank=True,
        help_text='Item ID on the source platform (e.g. LZT item_id, Eldorado UUID)',
    )
    ref_key = models.CharField(
        max_length=8, blank=True, default='',
        help_text='Unique reference key (#ABC1234) for traceability',
    )

    # Purchase info
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    purchased_at = models.DateTimeField(null=True, blank=True)
    source_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='purchased_products',
        help_text='Integration account where this product was purchased from',
    )

    # Dropship origin
    product_origin = models.ForeignKey(
        'inventory.DropshipProduct',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='owned_products',
        help_text='DropshipProduct this was purchased from (if dropship flow)',
    )

    # Raw data
    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'owned_products'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['category', 'login'],
                name='unique_owned_product_canonical',
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['-purchased_at']),
            models.Index(fields=['source_product_id']),
            models.Index(fields=['ref_key']),
        ]

    def __str__(self):
        return f"{self.category.title} - {self.login}"

    def save(self, *args, **kwargs):
        if self.password and not self.password_hash:
            self.password_hash = hashlib.sha256(self.password.encode()).hexdigest()
        super().save(*args, **kwargs)


class DropshipProduct(models.Model):
    source_product_id = models.CharField(
        max_length=128,
        help_text='Item ID on the source platform (numeric for LZT, UUID for Eldorado)',
    )
    source_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='dropship_products',
        help_text='Source integration account',
    )
    status = models.CharField(
        max_length=20,
        choices=DropshipProductStatus.choices,
        default=DropshipProductStatus.LISTED,
    )

    # Product info
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    product_title = models.CharField(max_length=500)
    source_url = models.URLField(max_length=500, blank=True)

    # Classification
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='dropship_products',
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='dropship_products',
    )

    # Raw data
    raw_data = models.JSONField(default=dict, blank=True)

    # Timestamps
    last_checked_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dropship_products'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source_account', 'source_product_id'],
                name='unique_dropship_product',
            ),
        ]
        indexes = [
            models.Index(fields=['status'], name='ds_product_status_idx'),
            models.Index(fields=['-created_at'], name='ds_product_created_idx'),
            models.Index(fields=['source_account', 'status'], name='ds_product_account_status_idx'),
            models.Index(
                fields=['source_account', 'status', 'last_checked_at'],
                name='ds_prod_status_checked_idx',
            ),
            models.Index(
                fields=['status', 'game', '-created_at'],
                name='ds_prod_stat_game_creat_idx',
            ),
        ]

    def __str__(self):
        return f"{self.product_title} ({self.source_product_id})"
