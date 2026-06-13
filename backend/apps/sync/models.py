from django.db import models
from django.utils import timezone

from .enums import (
    ResourceType,
    SyncMode,
    ParseStatus,
    CheckpointStatus,
    SyncRunStatus,
    SyncLogLevel,
)


class RawPayload(models.Model):
    """Raw provider payload stored before parsing.

    Design: latest-snapshot with upsert keyed on
    (integration_account, resource_type, remote_id).

    When the same remote item is fetched again:
    - If payload_hash differs → update payload, reset parse_status to pending
    - If payload_hash matches → update last_seen_at only

    This keeps the table bounded to one row per remote item while still
    allowing replay/reprocess of the latest version.
    """

    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='raw_payloads',
    )
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
    )
    remote_id = models.CharField(
        max_length=255,
        help_text='ID of this item on the remote provider',
    )

    payload = models.JSONField(
        help_text='Raw JSON response from provider',
    )
    payload_hash = models.CharField(
        max_length=64,
        help_text='SHA-256 of serialised payload for change detection',
    )

    first_seen_at = models.DateTimeField(
        help_text='When this remote item was first ingested',
    )
    last_seen_at = models.DateTimeField(
        help_text='When this remote item was last seen in a fetch',
    )
    fetched_at = models.DateTimeField(
        help_text='Timestamp of the fetch that last wrote this row',
    )

    parse_status = models.CharField(
        max_length=20,
        choices=ParseStatus.choices,
        default=ParseStatus.PENDING,
    )
    parse_error = models.TextField(
        blank=True,
        help_text='Traceback or message when parse_status is failed',
    )
    parsed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text='Optional metadata (provider page info, fetch context, etc.)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_raw_payloads'
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'resource_type', 'remote_id'],
                name='unique_account_resource_remote',
            ),
        ]
        indexes = [
            models.Index(fields=['resource_type', 'parse_status']),
            models.Index(fields=['integration_account', 'resource_type', 'parse_status']),
            models.Index(fields=['fetched_at']),
        ]
        ordering = ['-fetched_at']

    def __str__(self):
        return f"{self.resource_type}:{self.remote_id} ({self.parse_status})"


class SyncCheckpoint(models.Model):
    """Tracks cursor/resume state for a sync stream.

    One row per (integration_account, resource_type, mode) combination.
    The checkpoint only advances after raw payloads are safely persisted.
    """

    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='sync_checkpoints',
    )
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
    )
    mode = models.CharField(
        max_length=20,
        choices=SyncMode.choices,
    )

    cursor = models.TextField(
        blank=True,
        help_text='Opaque cursor value for the next page/batch (provider-specific)',
    )
    last_seen_remote_id = models.CharField(
        max_length=255,
        blank=True,
        help_text='Last remote ID successfully ingested',
    )
    last_seen_remote_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp of the last remote item ingested',
    )

    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the last sync run started for this checkpoint',
    )
    status = models.CharField(
        max_length=20,
        choices=CheckpointStatus.choices,
        default=CheckpointStatus.ACTIVE,
    )

    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text='Provider-specific checkpoint context',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_checkpoints'
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'resource_type', 'mode'],
                name='unique_account_resource_mode',
            ),
        ]
        ordering = ['-updated_at']

    def __str__(self):
        return (
            f"{self.integration_account} / {self.resource_type} / {self.mode} "
            f"({self.status})"
        )

    def advance(self, remote_id: str, remote_timestamp=None, cursor: str = ''):
        """Advance checkpoint after a batch is safely persisted."""
        self.last_seen_remote_id = remote_id
        self.cursor = cursor
        if remote_timestamp:
            self.last_seen_remote_timestamp = remote_timestamp
        self.last_run_at = timezone.now()
        self.save(update_fields=[
            'last_seen_remote_id',
            'last_seen_remote_timestamp',
            'cursor',
            'last_run_at',
            'updated_at',
        ])


class SyncRun(models.Model):
    """Audit log for each sync execution."""

    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='sync_runs',
    )
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
    )
    mode = models.CharField(
        max_length=20,
        choices=SyncMode.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=SyncRunStatus.choices,
        default=SyncRunStatus.RUNNING,
    )

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    processed_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text='Run-level metadata (error summary, last page, etc.)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_runs'
        indexes = [
            models.Index(fields=['integration_account', 'resource_type']),
            models.Index(fields=['status']),
            models.Index(fields=['-started_at']),
        ]
        ordering = ['-started_at']

    def __str__(self):
        return (
            f"SyncRun {self.pk} — {self.resource_type}/{self.mode} "
            f"({self.status})"
        )

    def finish(self, status: str, **counters):
        """Mark run as finished with final counters."""
        self.status = status
        self.finished_at = timezone.now()
        for key, value in counters.items():
            if hasattr(self, key):
                setattr(self, key, value)
        update_fields = [
            'status', 'finished_at', 'updated_at',
            'processed_count', 'created_count', 'updated_count', 'error_count',
        ]
        self.save(update_fields=update_fields)


class SyncLog(models.Model):
    """Structured log for sync orchestrator events.

    Used for: sync chain progress, cross-platform offer removal results,
    unlinked order warnings, and error tracking.  Viewable in Django Admin.
    """

    task_name = models.CharField(
        max_length=100,
        help_text='Sync task identifier (e.g. lzt_sync, offer_sync, reconcile)',
    )
    level = models.CharField(
        max_length=10,
        choices=SyncLogLevel.choices,
        default=SyncLogLevel.INFO,
    )
    message = models.TextField(
        help_text='Human-readable summary of what happened',
    )
    detail = models.JSONField(
        default=dict,
        blank=True,
        help_text='Machine-readable details (counters, IDs, tracebacks)',
    )

    # Context FKs — all optional, link to relevant entity
    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_logs',
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_logs',
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_logs',
    )
    owned_product = models.ForeignKey(
        'inventory.OwnedProduct',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_logs',
    )
    sync_run = models.ForeignKey(
        'sync.SyncRun',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_logs',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sync_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['task_name', '-created_at']),
            models.Index(fields=['level', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.level}] {self.task_name}: {self.message[:80]}"


class SyncFeatureFlag(models.Model):
    """Runtime feature toggles for sync chain steps.

    Each row represents a toggleable sync feature (e.g. cross-platform
    reconciliation, review monitor, order status refresh).  Checked at
    runtime via ``is_sync_feature_enabled(key)`` — no restart needed.
    """

    key = models.CharField(
        max_length=100,
        unique=True,
        help_text='Unique identifier (e.g. sync.reconcile, sync.review_monitor)',
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text='Uncheck to disable this sync feature at runtime',
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text='Human-readable description of what this flag controls',
    )
    value = models.JSONField(
        null=True, blank=True,
        help_text='Optional config value (e.g. {"interval_minutes": 30})',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_feature_flags'
        ordering = ['key']
        verbose_name = 'Sync Feature Flag'
        verbose_name_plural = 'Sync Feature Flags'

    def __str__(self):
        state = 'ON' if self.is_enabled else 'OFF'
        return f'{self.key} [{state}]'
