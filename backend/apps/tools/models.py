from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class RobuxCrateBatch(models.Model):
    """Groups N RobuxCrate orders created in a single user request."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        PARTIAL = 'partial', 'Partial Success'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_request_id = models.UUIDField(unique=True, help_text='Idempotency key from client')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='robuxcrate_batches',
    )
    roblox_username = models.CharField(max_length=50)
    roblox_user_id = models.BigIntegerField(null=True, blank=True)
    place_id = models.BigIntegerField()
    place_name = models.CharField(max_length=200, blank=True)
    robux_amount = models.PositiveIntegerField()
    quantity = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
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
        PROGRESS = 'progress', 'In Progress'
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
