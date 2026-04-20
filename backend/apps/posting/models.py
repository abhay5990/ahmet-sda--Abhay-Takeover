from django.db import models


class PostingJobStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class PostingJobItemStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    SKIPPED = 'skipped', 'Skipped'


class PostingLogLevel(models.TextChoices):
    INFO = 'info', 'Info'
    WARNING = 'warning', 'Warning'
    ERROR = 'error', 'Error'
    SUCCESS = 'success', 'Success'


class PostingJob(models.Model):
    """Stock posting batch — groups multiple PostingJobItems."""

    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='posting_jobs',
    )
    source_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posting_jobs_as_source',
        help_text='Fallback account for resolving missing products (e.g. LZT)',
    )
    settings = models.JSONField(
        default=dict, blank=True,
        help_text='Store slug-keyed pricing/config snapshot from UI',
    )
    status = models.CharField(
        max_length=20,
        choices=PostingJobStatus.choices,
        default=PostingJobStatus.PENDING,
    )
    total_count = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    fail_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'posting_jobs'
        ordering = ['-created_at']

    def __str__(self):
        return f"Job #{self.pk} — {self.game} ({self.status})"


class PostingJobItem(models.Model):
    """Single posting attempt: 1 login × 1 store."""

    job = models.ForeignKey(
        PostingJob,
        on_delete=models.CASCADE,
        related_name='items',
    )
    login = models.CharField(
        max_length=255,
        default='',
        help_text='Login identifier — always populated, primary key for tracking',
    )
    owned_product = models.ForeignKey(
        'inventory.OwnedProduct',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posting_items',
        help_text='Resolved after job creation; null until orchestrator resolves',
    )
    store = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='posting_items',
    )
    marketplace = models.CharField(
        max_length=30,
        help_text='Denormalized from store.provider for query performance',
    )
    status = models.CharField(
        max_length=20,
        choices=PostingJobItemStatus.choices,
        default=PostingJobItemStatus.PENDING,
    )
    error_message = models.TextField(blank=True)
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posting_items',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'posting_job_items'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['job', 'status']),
        ]

    def __str__(self):
        login_display = self.login or (self.owned_product.login if self.owned_product else '???')
        return f"Item #{self.pk} — {login_display} → {self.store.name} ({self.status})"


class PostingDefault(models.Model):
    """Remembers last-used pricing/config per game+marketplace (stock only)."""

    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='posting_defaults',
    )
    marketplace = models.CharField(max_length=30)

    # Pricing tiers
    multiplier_low = models.DecimalField(
        max_digits=5, decimal_places=2, default=2.0,
        help_text='Multiplier for price <= $10',
    )
    multiplier_mid = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.8,
        help_text='Multiplier for $10 < price <= $100',
    )
    multiplier_high = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.5,
        help_text='Multiplier for price > $100',
    )
    min_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Floor price — result never goes below this',
    )
    forced_ending = models.DecimalField(
        max_digits=3, decimal_places=2, null=True, blank=True, default=0.99,
        help_text='Force cents ending (e.g. 0.99). Null = disabled.',
    )

    # Site-specific
    sub_platform = models.CharField(
        max_length=20, blank=True,
        help_text='Last selected sub-platform (PC/PSN/Xbox/Auto)',
    )
    account_type = models.CharField(
        max_length=50, blank=True,
        help_text='Last selected account type',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'posting_defaults'
        unique_together = [('game', 'marketplace')]

    def __str__(self):
        return f"{self.game} — {self.marketplace}"


class SubplatformLimit(models.Model):
    """Max offer limits per store × game × sub-platform. Shared by stock + dropship."""

    store = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='subplatform_limits',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='subplatform_limits',
    )
    sub_platform = models.CharField(
        max_length=20,
        help_text='PC, PSN, Xbox, etc.',
    )
    max_offers = models.IntegerField(
        help_text='Maximum offers allowed on this sub-platform',
    )
    stock_reserve = models.IntegerField(
        default=0,
        help_text='Slots reserved for stock (dropship cannot use these)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subplatform_limits'
        unique_together = [('store', 'game', 'sub_platform')]

    def __str__(self):
        return f"{self.store.name} — {self.game} — {self.sub_platform} (max={self.max_offers})"


class PostingLog(models.Model):
    """Operational log for posting activities (stock + dropship shared)."""

    task_name = models.CharField(
        max_length=50,
        help_text='stock_post, dropship_poster, dropship_cleaner',
    )
    level = models.CharField(
        max_length=10,
        choices=PostingLogLevel.choices,
        default=PostingLogLevel.INFO,
    )
    message = models.CharField(max_length=255)
    detail = models.JSONField(default=dict, blank=True)
    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posting_logs',
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'posting_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task_name', '-created_at'], name='posting_log_task_created_idx'),
            models.Index(fields=['level'], name='posting_log_level_idx'),
        ]

    def __str__(self):
        return f"[{self.level}] {self.task_name}: {self.message}"


class DropshippingJobConfig(models.Model):
    """Dropship poster config — which source account posts to which target store+game.

    Uses the 3-concept worker state model (Intent / Actual / Condition):
    - Intent:     ``enabled`` — should the poster run?
    - Actual:     ``poster_running`` — is the thread alive right now?
    - Condition:  ``disabled_reason`` — why was it disabled (empty = user choice)?
    """

    source_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='dropship_source_configs',
        help_text='Source buy account used to fetch items (e.g. LZT)',
    )
    store = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='dropship_target_configs',
        help_text='Target sell account (gameboost, eldorado, etc.)',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='dropship_configs',
    )
    item_delay = models.DecimalField(
        max_digits=5, decimal_places=1, default=3.0,
        help_text='Seconds between marketplace POSTs',
    )
    source_delay = models.DecimalField(
        max_digits=5, decimal_places=1, default=1.0,
        help_text='Seconds between source fetches',
    )

    # --- Poster worker: 3-concept state (Intent / Actual / Condition) ---
    enabled = models.BooleanField(
        default=True,
        help_text='INTENT — should the poster thread run?',
    )
    disabled_reason = models.CharField(
        max_length=255, blank=True, default='',
        help_text='CONDITION — why disabled (empty = user choice, non-empty = system)',
    )
    poster_running = models.BooleanField(
        default=False,
        help_text='ACTUAL — is the poster thread alive right now?',
    )
    poster_cycle_interval = models.PositiveIntegerField(
        default=300,
        help_text='Seconds between poster cycles (default 5 min)',
    )
    poster_last_cycle_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the poster last completed a full cycle',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dropshipping_job_configs'
        unique_together = [('source_account', 'store', 'game')]

    def __str__(self):
        return f"{self.source_account.name} → {self.store.name} ({self.game})"


class DropshipTargetURL(models.Model):
    """LZT filter URL with per-URL pricing — attached to a DropshippingJobConfig."""

    config = models.ForeignKey(
        DropshippingJobConfig,
        on_delete=models.CASCADE,
        related_name='target_urls',
    )
    url = models.URLField(
        max_length=500,
        help_text='LZT filter URL (e.g. https://lzt.market/fortnite?pmin=5)',
    )
    enabled = models.BooleanField(default=True)

    # Pricing (per-URL, independent from stock PostingDefault)
    multiplier_low = models.DecimalField(
        max_digits=5, decimal_places=2, default=2.0,
        help_text='Multiplier for price <= $10',
    )
    multiplier_mid = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.8,
        help_text='Multiplier for $10 < price <= $100',
    )
    multiplier_high = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.5,
        help_text='Multiplier for price > $100',
    )
    min_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Floor price',
    )
    forced_ending = models.DecimalField(
        max_digits=3, decimal_places=2, null=True, blank=True, default=0.99,
        help_text='Force cents ending (e.g. 0.99). Null = disabled.',
    )

    # Stats
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    error_count = models.IntegerField(default=0)
    items_found = models.IntegerField(default=0)
    items_posted = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dropship_target_urls'

    def __str__(self):
        return f"{self.config} — {self.url[:60]}"


class SchedulerHeartbeat(models.Model):
    """Scheduler process liveness — heartbeat only, no worker state."""

    service_name = models.CharField(
        max_length=50, unique=True,
        help_text='Scheduler identifier, e.g. "dropship"',
    )
    last_seen = models.DateTimeField(
        help_text='Last heartbeat timestamp — stale if >60s ago',
    )
    pid = models.IntegerField(
        null=True, blank=True,
        help_text='OS process ID (debug/monitoring)',
    )
    started_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the scheduler process started (set by management command)',
    )
    class Meta:
        db_table = 'scheduler_heartbeats'

    def __str__(self):
        return f"Scheduler: {self.service_name} (last seen: {self.last_seen})"


class CleanerConfig(models.Model):
    """Dropship cleaner config — one per source account.

    Uses the 3-concept worker state model (Intent / Actual / Condition):
    - Intent:     ``enabled`` — should the cleaner run?
    - Actual:     ``running`` — is the thread alive right now?
    - Condition:  ``disabled_reason`` — why was it disabled (empty = user choice)?

    Cleaner checks all DropshipProducts belonging to ``source_account``,
    regardless of which store/game they were posted to.
    """

    source_account = models.OneToOneField(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='cleaner_config',
        help_text='Source account whose products this cleaner monitors',
    )

    # --- Cleaner worker: 3-concept state (Intent / Actual / Condition) ---
    enabled = models.BooleanField(
        default=True,
        help_text='INTENT — should the cleaner thread run?',
    )
    disabled_reason = models.CharField(
        max_length=255, blank=True, default='',
        help_text='CONDITION — why disabled (empty = user choice, non-empty = system)',
    )
    running = models.BooleanField(
        default=False,
        help_text='ACTUAL — is the cleaner thread alive right now?',
    )
    cycle_interval = models.PositiveIntegerField(
        default=600,
        help_text='Seconds between cleaner cycles (default 10 min)',
    )
    last_cycle_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the cleaner last completed a full cycle',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cleaner_configs'

    def __str__(self):
        return f"Cleaner: {self.source_account.name} ({'ON' if self.enabled else 'OFF'})"
