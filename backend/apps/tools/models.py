from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class RobuxCrateBatch(models.Model):
    """Groups N RobuxCrate orders created in a single user request."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        ERROR = 'error', 'Error'
        CANCELLED = 'cancelled', 'Cancelled'

    class Marketplace(models.TextChoices):
        ELDORADO = 'eldorado', 'Eldorado'
        GAMEBOOST = 'gameboost', 'GameBoost'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_request_id = models.UUIDField(unique=True, help_text='Idempotency key from client')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='robuxcrate_batches',
    )

    # Marketplace integration
    marketplace = models.CharField(max_length=20, choices=Marketplace.choices)
    marketplace_order_id = models.CharField(max_length=100, help_text='Order ID on the marketplace (e.g. Eldorado order ID)')
    marketplace_store = models.ForeignKey(
        'integrations.IntegrationCredential',
        on_delete=models.SET_NULL,
        null=True,
        related_name='robuxcrate_batches',
        help_text='Which marketplace store/account to use for delivery',
    )

    # RbxCrate merchant
    merchant = models.ForeignKey(
        'integrations.ServiceCredential',
        on_delete=models.SET_NULL,
        null=True,
        related_name='robuxcrate_batches',
        help_text='Which RbxCrate merchant (API key) to use',
    )

    # Roblox / order details
    roblox_username = models.CharField(max_length=50)
    roblox_user_id = models.BigIntegerField(null=True, blank=True)
    place_id = models.BigIntegerField()
    place_name = models.CharField(max_length=200, blank=True)

    # Auto-place: when True, the batch tries each candidate place in order
    # until one succeeds (a place fails when RbxCrate returns GAMEPASS_NOT_FOUND).
    # place_id/place_name above always reflect the *currently active* candidate.
    auto_place = models.BooleanField(default=False)
    place_candidates = models.JSONField(
        default=list,
        blank=True,
        help_text='Ordered list of {place_id, name} candidates tried in auto-place mode',
    )
    place_attempt_index = models.PositiveSmallIntegerField(
        default=0,
        help_text='Index into place_candidates of the currently active place',
    )

    robux_amount = models.PositiveIntegerField()
    quantity = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Delivery tracking
    delivery_attempted_at = models.DateTimeField(null=True, blank=True)
    delivery_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Batch {self.id!s:.8} — {self.roblox_username} {self.quantity}x{self.robux_amount}R$'


class RobuxCrateOrder(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        QUEUED = 'queued', 'Queued'
        COMPLETED = 'completed', 'Completed'
        ERROR = 'error', 'Error'
        CANCELLED = 'cancelled', 'Cancelled'
        UNKNOWN = 'unknown', 'Unknown'

    FINAL_STATUSES = frozenset({
        Status.COMPLETED,
        Status.ERROR,
        Status.CANCELLED,
    })

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        RobuxCrateBatch,
        on_delete=models.CASCADE,
        related_name='orders',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='robuxcrate_orders',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    raw_provider_status = models.CharField(max_length=50, blank=True)
    rbxcrate_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    last_status_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='idx_rbxorder_status'),
            models.Index(fields=['created_at'], name='idx_rbxorder_created'),
        ]

    def __str__(self):
        return f'Order {self.id!s:.8} ({self.status})'
