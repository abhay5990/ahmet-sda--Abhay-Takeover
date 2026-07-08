from pathlib import Path
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models


def posting_image_preset_upload_to(instance, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in {'.jpg', '.jpeg', '.png'}:
        ext = '.png'
    token = instance.sha256[:24] if instance.sha256 else uuid.uuid4().hex[:24]
    return f'posting/image_presets/game_{instance.game_id}/{token}{ext}'


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
    # Seller filter — if set, only items from this seller are dropshipped
    seller_username = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Eldorado seller username to filter by (e.g. OdbougShop). Empty = all sellers.',
    )
    exchange_rate = models.DecimalField(
        max_digits=6, decimal_places=4, null=True, blank=True, default=0.87,
        help_text='USD→EUR conversion rate for Gameboost. Null = no conversion.',
    )

    # Content templates (optional — null means use legacy generators)
    title_template = models.ForeignKey(
        'posting.ContentTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posting_defaults_as_title',
        limit_choices_to={'template_type': 'title'},
        help_text='Selected title template. Null = use legacy title generator.',
    )
    description_template = models.ForeignKey(
        'posting.ContentTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='posting_defaults_as_description',
        limit_choices_to={'template_type': 'description'},
        help_text='Selected description template. Null = use legacy description generator.',
    )

    # Site-specific
    variant = models.CharField(
        max_length=20, blank=True,
        help_text='Last selected variant slug (pc/psn/xbox/auto)',
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

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if self.title_template_id:
            self._validate_template_fk(
                self.title_template, 'title', 'title_template', errors,
            )
        if self.description_template_id:
            self._validate_template_fk(
                self.description_template, 'description', 'description_template', errors,
            )
        if errors:
            raise ValidationError(errors)

    def _validate_template_fk(self, template, expected_type, field_name, errors):
        """Ensure the FK points to a template matching this default's game, marketplace, and type."""
        if template.game_id != self.game_id:
            errors[field_name] = (
                f'Template "{template.name}" belongs to a different game.'
            )
        elif template.marketplace != self.marketplace:
            errors[field_name] = (
                f'Template "{template.name}" is for {template.marketplace}, '
                f'not {self.marketplace}.'
            )
        elif template.template_type != expected_type:
            errors[field_name] = (
                f'Template "{template.name}" is a {template.template_type} template, '
                f'expected {expected_type}.'
            )


class CosmeticList(models.Model):
    """User-defined cosmetic matching list for template engine.

    Each list defines a set of item names that are matched against the
    account's cosmetic_titles (or another source field via match_field).
    Lists are processed in priority order with automatic deduplication:
    items matched by a higher-priority list are excluded from lower ones.

    The list's ``slug`` becomes a template field name, e.g. {og_skins}.
    """

    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='cosmetic_lists',
    )
    name = models.CharField(
        max_length=100,
        help_text='Display name, e.g. "OG Skins"',
    )
    slug = models.SlugField(
        max_length=50,
        help_text='Template field name, e.g. "og_skins" -> {og_skins}',
    )
    items = models.JSONField(
        default=list,
        help_text='List of item names to match against, e.g. ["Renegade Raider", "Black Knight"]',
    )
    match_field = models.CharField(
        max_length=50,
        default='cosmetic_titles',
        help_text='Account field to match against (e.g. cosmetic_titles)',
    )
    priority = models.PositiveIntegerField(
        default=0,
        help_text='Processing order (lower = first). Higher priority lists claim items first.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive lists are skipped during context building.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cosmetic_lists'
        unique_together = [('game', 'slug')]
        ordering = ['game', 'priority', 'name']

    def __str__(self):
        return f"{self.name} ({self.game} / priority={self.priority})"


class ContentTemplate(models.Model):
    """User-created content template with {field_name} placeholders.

    Users write plain text with placeholders like ``{rank}``, ``{level}``,
    ``{valuable_skins}`` etc.  At posting time, placeholders are resolved
    from the game's resolved account model.

    Templates are scoped to game + marketplace + type (title/description).
    A user can create multiple templates per combination and select which
    one to use at posting time.
    """

    TEMPLATE_TYPE_CHOICES = [
        ('title', 'Title'),
        ('description', 'Description'),
    ]
    MARKETPLACE_CHOICES = [
        ('eldorado', 'Eldorado'),
        ('gameboost', 'GameBoost'),
        ('g2g', 'G2G'),
        ('playerauctions', 'PlayerAuctions'),
    ]

    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='content_templates',
    )
    marketplace = models.CharField(
        max_length=30,
        choices=MARKETPLACE_CHOICES,
    )
    template_type = models.CharField(
        max_length=20,
        choices=TEMPLATE_TYPE_CHOICES,
    )
    name = models.CharField(
        max_length=100,
        help_text='User-friendly template name, e.g. "Detailed Valorant Title"',
    )
    body = models.TextField(
        help_text='Template text with {field_name} placeholders',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_templates'
        constraints = [
            models.UniqueConstraint(
                fields=['game', 'marketplace', 'name', 'template_type'],
                name='unique_content_template',
            ),
        ]
        indexes = [
            models.Index(
                fields=['game', 'marketplace', 'template_type'],
                name='content_template_lookup_idx',
            ),
        ]
        ordering = ['game__name', 'marketplace', 'template_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.game} / {self.marketplace} / {self.template_type})"

    def clean(self):
        super().clean()
        from payload_pipeline.content_templates import (
            TemplateValidationError,
            validate_template,
        )
        try:
            validate_template(
                self.body,
                template_type=self.template_type,
            )
        except TemplateValidationError as exc:
            raise ValidationError({'body': str(exc)}) from exc


class PostingImagePreset(models.Model):
    """Reusable marketplace media shared per game for posting flows."""

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posting_image_presets',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='posting_image_presets',
    )
    name = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to=posting_image_preset_upload_to)
    sha256 = models.CharField(max_length=64, db_index=True)
    mime_type = models.CharField(max_length=50, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'posting_image_presets'
        ordering = ['-last_used_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['game', 'sha256'],
                name='unique_posting_image_preset_game_hash',
            ),
        ]
        indexes = [
            models.Index(
                fields=['game', 'is_active'],
                name='posting_img_game_active_idx',
            ),
        ]

    def __str__(self):
        return self.name or f"Image preset #{self.pk}"


# ── Game Variant System ──────────────────────────────────────────


class GameVariant(models.Model):
    """A dimension that differentiates listings for a game (platform, region, etc.).

    Examples:
        Fortnite + platform + "pc" → "PC"
        Valorant + region + "na"   → "North America"
        GTA V    + platform + "ps5" → "PlayStation 5"
    """

    class VariantType(models.TextChoices):
        PLATFORM = 'platform', 'Platform'
        REGION = 'region', 'Region'

    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='variants',
    )
    type = models.CharField(
        max_length=20,
        choices=VariantType.choices,
    )
    slug = models.CharField(
        max_length=30,
        help_text='Internal key: pc, psn, na, euw, etc.',
    )
    label = models.CharField(
        max_length=60,
        help_text='Display name: PC, PlayStation, North America',
    )
    source_key = models.CharField(
        max_length=60,
        blank=True,
        help_text='Account field value for lookup. Empty = use slug.',
    )
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'game_variants'
        unique_together = [('game', 'type', 'slug')]
        ordering = ['game', 'type', 'sort_order']

    def __str__(self):
        return f"{self.game} — {self.type}/{self.slug} ({self.label})"


class GameVariantMapping(models.Model):
    """Marketplace-specific external ID for a game variant."""

    class Marketplace(models.TextChoices):
        ELDORADO = 'eldorado', 'Eldorado'
        GAMEBOOST = 'gameboost', 'GameBoost'
        PLAYERAUCTIONS = 'playerauctions', 'PlayerAuctions'

    variant = models.ForeignKey(
        GameVariant,
        on_delete=models.CASCADE,
        related_name='mappings',
    )
    marketplace = models.CharField(
        max_length=20,
        choices=Marketplace.choices,
    )
    external_id = models.CharField(
        max_length=30,
        help_text='Marketplace-specific ID: "0", "9874", "1-0"',
    )
    external_name = models.CharField(
        max_length=60,
        blank=True,
        help_text='Optional display name on the marketplace',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'game_variant_mappings'
        unique_together = [('variant', 'marketplace')]

    def __str__(self):
        return f"{self.variant} → {self.marketplace}:{self.external_id}"


class GameVariantLimit(models.Model):
    """Capacity limit per store × variant. Replaces SubplatformLimit."""

    store = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='variant_limits',
    )
    variant = models.ForeignKey(
        GameVariant,
        on_delete=models.CASCADE,
        related_name='limits',
    )
    max_offers = models.PositiveIntegerField(
        help_text='Maximum offers allowed for this variant',
    )
    stock_reserve = models.PositiveIntegerField(
        default=0,
        help_text='Slots reserved for stock (dropship cannot use these)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'game_variant_limits'
        unique_together = [('store', 'variant')]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_reserve__lte=models.F('max_offers')),
                name='stock_reserve_lte_max_offers',
            ),
        ]

    def __str__(self):
        return f"{self.store.name} — {self.variant} (max={self.max_offers})"


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
        help_text='Source filter URL or query string (e.g. gameId=259&category=CustomItem)',
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
    exchange_rate = models.DecimalField(
        max_digits=6, decimal_places=4, null=True, blank=True, default=0.87,
        help_text='USD→EUR conversion rate for Gameboost. Null = no conversion.',
    )

    # --- Processing state (UI: hangi URL su an isleniyor) ---
    PROC_IDLE = 'idle'
    PROC_FETCHING = 'fetching'
    PROC_POSTING = 'posting'
    PROC_CHOICES = [
        (PROC_IDLE, 'Idle'),
        (PROC_FETCHING, 'Fetching'),
        (PROC_POSTING, 'Posting'),
    ]
    processing_state = models.CharField(
        max_length=10, choices=PROC_CHOICES, default=PROC_IDLE,
        help_text='Poster bu URL uzerinde su an ne yapiyor (canli gosterge)',
    )

    # --- Stats ---
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    error_count = models.IntegerField(default=0)

    # Son cycle kirilimi: found = (found - new) + new ; new >= posted
    cycle_found = models.IntegerField(default=0, help_text='Son cycle filtrede gorulen toplam (duplicate dahil)')
    cycle_new = models.IntegerField(default=0, help_text='Son cycle yeni (duplicate olmayan) item')
    cycle_posted = models.IntegerField(default=0, help_text='Son cycle gercekten basilan')

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


# ── Credential Spec ──────────────────────────────────────────────


class CredentialSpec(models.Model):
    """Configurable credential field definition + marketplace format templates.

    Each spec defines which credential fields are collected (login, password,
    email, platform-specific extras) and how they are formatted for each
    marketplace when pushing to offers.

    Resolution priority:
    1. Explicit pool.credential_spec
    2. Variant-level spec (via pool.variant)
    3. Game-level default spec (variant=NULL)
    4. Code-level preset fallback
    """

    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.CASCADE,
        related_name='credential_specs',
    )
    variant = models.ForeignKey(
        'posting.GameVariant',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='credential_specs',
        help_text='If set, this spec applies to a specific variant. NULL = game default.',
    )
    name = models.CharField(max_length=100, blank=True)

    fields = models.JSONField(
        help_text='List of CredentialFieldSchema dicts: [{key, label, required, role}, ...]',
    )
    format_templates = models.JSONField(
        default=dict,
        blank=True,
        help_text='Marketplace-keyed format templates: {eldorado: "...", gameboost: "...", playerauctions: {...}}',
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'credential_specs'
        constraints = [
            models.UniqueConstraint(
                fields=['game'],
                condition=models.Q(variant__isnull=True),
                name='unique_game_default_spec',
            ),
            models.UniqueConstraint(
                fields=['variant'],
                condition=models.Q(variant__isnull=False),
                name='unique_variant_spec',
            ),
        ]
        ordering = ['game', 'name']

    def save(self, **kwargs):
        if not self.name:
            game_name = self.game.name if self.game_id else '?'
            if self.variant_id:
                self.name = f"{game_name} — {self.variant.label}"
            else:
                self.name = f"{game_name} (default)"
        super().save(**kwargs)

    def __str__(self):
        variant_str = f" / {self.variant.label}" if self.variant else " (default)"
        return f"{self.name} — {self.game}{variant_str}"

    def clean(self):
        super().clean()
        from apps.posting.services.pool.presets import (
            validate_credential_fields,
            validate_format_templates,
        )
        validate_credential_fields(self.fields)
        validate_format_templates(self.format_templates, self.fields)

        if self.variant_id and self.variant.game_id != self.game_id:
            raise ValidationError(
                "CredentialSpec.variant must belong to CredentialSpec.game"
            )


# ── Auto Restock (Offer Pool) ────────────────────────────────────


class OfferPoolStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    PAUSED = 'paused', 'Paused'
    ARCHIVED = 'archived', 'Archived'
    # Transitional legacy value. Depletion is computed health in new code.
    DEPLETED = 'depleted', 'Depleted (Legacy)'


class PoolOfferStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    PAUSED = 'paused', 'Paused'
    DETACHED = 'detached', 'Detached'
    ERROR = 'error', 'Error'


class PoolOfferStrategy(models.TextChoices):
    APPEND = 'append', 'Append Credentials'
    CLONE = 'clone', 'Clone Offer'


class OfferPoolItemStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RESERVED = 'reserved', 'Reserved'
    QUEUED = 'queued', 'Queued'
    PUSHED = 'pushed', 'Pushed'
    FAILED = 'failed', 'Failed'
    CONSUMED = 'consumed', 'Consumed'


class OfferPoolActiveOfferStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    SOLD = 'sold', 'Sold'
    FAILED = 'failed', 'Failed'
    DELISTED = 'delisted', 'Delisted'


class OfferPool(models.Model):
    """Marketplace-independent stock pool.

    Legacy listing/store/config fields remain nullable during the expand and
    cutover releases. New code uses PoolOffer for all remote configuration.
    """

    Strategy = PoolOfferStrategy

    name = models.CharField(max_length=255, null=True, blank=True)

    listing = models.ForeignKey(
        'listings.Listing',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='offer_pools',
        help_text='Deprecated: use pool_offers instead',
    )
    game = models.ForeignKey(
        'inventory.Game',
        on_delete=models.PROTECT,
        related_name='offer_pools',
    )
    variant = models.ForeignKey(
        'posting.GameVariant',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='offer_pools',
    )
    store = models.ForeignKey(
        'integrations.IntegrationAccount',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='offer_pools',
        help_text='Deprecated: derive store from PoolOffer.listing',
    )
    credential_spec = models.ForeignKey(
        'posting.CredentialSpec',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='pools',
        help_text='Credential field definition + format templates. NULL = use resolver chain.',
    )
    strategy = models.CharField(
        max_length=10,
        choices=PoolOfferStrategy.choices,
        null=True,
        blank=True,
        help_text='Deprecated: strategy is configured per PoolOffer',
    )
    status = models.CharField(
        max_length=10,
        choices=OfferPoolStatus.choices,
        default=OfferPoolStatus.ACTIVE,
    )

    # Thresholds
    threshold = models.PositiveIntegerField(
        default=10,
        help_text='Trigger replenish when remote credential count drops below this',
    )
    target_count = models.PositiveIntegerField(
        default=50,
        help_text='Fill up to this many credentials per replenish cycle',
    )
    max_concurrent = models.PositiveIntegerField(
        default=1,
        help_text='PA clone strategy: max simultaneous offers from this pool',
    )

    # Monitoring state
    current_remote_count = models.IntegerField(
        null=True, blank=True,
        help_text='Last known credential count on the remote offer',
    )
    last_checked_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Last time remote count was checked',
    )
    last_replenished_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Last time credentials were pushed',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'offer_pools'
        constraints = [
            models.UniqueConstraint(
                fields=['listing'],
                name='unique_pool_per_listing',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name or f'Pool #{self.pk}'} ({self.status})"

    @property
    def pending_count(self) -> int:
        return self.items.filter(
            status=OfferPoolItemStatus.PENDING,
            pool_offer__isnull=True,
            reservation__isnull=True,
        ).count()

    @property
    def is_depleted(self) -> bool:
        return self.pending_count == 0

    @property
    def health(self) -> str:
        if self.status == OfferPoolStatus.ARCHIVED:
            return 'archived'
        if self.status == OfferPoolStatus.PAUSED:
            return 'paused'
        if not self.pool_offers.exclude(status=PoolOfferStatus.DETACHED).exists():
            return 'no_offers'
        if self.pool_offers.filter(status=PoolOfferStatus.ERROR).exists():
            return 'attention_required'
        return 'depleted' if self.is_depleted else 'healthy'

    def clean(self):
        super().clean()
        if not (self.name or '').strip():
            raise ValidationError({'name': 'Pool name is required.'})
        if self.variant_id and self.variant.game_id != self.game_id:
            raise ValidationError({'variant': 'Pool variant must belong to pool game.'})
        if self.credential_spec_id:
            if self.credential_spec.game_id != self.game_id:
                raise ValidationError({'credential_spec': 'Credential spec must belong to pool game.'})
            if (
                self.variant_id
                and self.credential_spec.variant_id
                and self.credential_spec.variant_id != self.variant_id
            ):
                raise ValidationError({'credential_spec': 'Credential spec variant must match pool variant.'})


class PoolOffer(models.Model):
    """One marketplace offer served by a stock pool."""

    pool = models.ForeignKey(
        OfferPool,
        on_delete=models.PROTECT,
        related_name='pool_offers',
    )
    listing = models.OneToOneField(
        'listings.Listing',
        on_delete=models.PROTECT,
        related_name='pool_offer',
    )
    strategy = models.CharField(max_length=10, choices=PoolOfferStrategy.choices)
    target_count = models.PositiveIntegerField(default=5)
    threshold = models.PositiveIntegerField(default=2)
    max_concurrent = models.PositiveIntegerField(null=True, blank=True)
    current_remote_count = models.PositiveIntegerField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_replenished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=PoolOfferStatus.choices,
        default=PoolOfferStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pool_offers'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(threshold__lte=models.F('target_count')),
                name='pool_offer_threshold_lte_target',
            ),
            models.CheckConstraint(
                condition=models.Q(threshold__gte=1, target_count__gte=1),
                name='pool_offer_positive_threshold_target',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        strategy=PoolOfferStrategy.APPEND,
                        max_concurrent__isnull=True,
                    )
                    | models.Q(
                        strategy=PoolOfferStrategy.CLONE,
                        max_concurrent__isnull=False,
                        max_concurrent__lte=10,
                        target_count__lte=models.F('max_concurrent'),
                    )
                ),
                name='pool_offer_strategy_capacity_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'pool'], name='pool_offer_status_pool_idx'),
            models.Index(fields=['last_checked_at'], name='pool_offer_checked_idx'),
        ]

    def __str__(self):
        return f"{self.pool} -> {self.listing}"

    @property
    def store(self):
        return self.listing.integration_account

    @property
    def marketplace(self) -> str:
        return self.store.provider if self.store else ''

    @property
    def can_replenish(self) -> bool:
        return (
            self.pool.status == OfferPoolStatus.ACTIVE
            and self.status == PoolOfferStatus.ACTIVE
        )

    @property
    def needs_replenish(self) -> bool:
        if not self.can_replenish:
            return False
        return (
            self.current_remote_count is None
            or self.current_remote_count < self.threshold
        )

    @classmethod
    def strategy_for_provider(cls, provider: str) -> str:
        if provider == 'playerauctions':
            return PoolOfferStrategy.CLONE
        if provider in {'eldorado', 'gameboost'}:
            return PoolOfferStrategy.APPEND
        raise ValidationError(f'Unsupported pool marketplace: {provider}')

    def clean(self):
        super().clean()
        listing = self.listing
        if listing.status != 'listed' or not listing.is_instant:
            raise ValidationError({'listing': 'Listing must be an active instant listing.'})
        if not listing.integration_account_id:
            raise ValidationError({'listing': 'Listing must have an integration account.'})
        if not listing.integration_account.is_active:
            raise ValidationError({'listing': 'Listing integration account must be active.'})
        try:
            credential = listing.integration_account.credential
        except ObjectDoesNotExist:
            credential = None
        if not credential or not credential.is_active:
            raise ValidationError({'listing': 'Listing integration account needs active credentials.'})
        if not listing.game_id or listing.game_id != self.pool.game_id:
            raise ValidationError({'listing': 'Listing game must match pool game.'})
        if self.pool.variant_id:
            from apps.posting.services.pool.spec_resolver import variant_value_contains_slug
            if not variant_value_contains_slug(listing.variant, self.pool.variant.slug):
                raise ValidationError({'listing': 'Listing variant must match pool variant.'})
        expected_strategy = self.strategy_for_provider(listing.integration_account.provider)
        if self.strategy != expected_strategy:
            raise ValidationError({'strategy': f'Strategy must be {expected_strategy} for this provider.'})
        if self.threshold < 1 or self.target_count < 1 or self.threshold > self.target_count:
            raise ValidationError({'threshold': 'Threshold must be between 1 and target_count.'})
        if self.strategy == PoolOfferStrategy.CLONE:
            if self.max_concurrent is None or not (
                self.target_count <= self.max_concurrent <= 10
            ):
                raise ValidationError({
                    'max_concurrent': 'Clone max must satisfy target_count <= max <= 10.',
                })
        elif self.max_concurrent is not None:
            raise ValidationError({'max_concurrent': 'Append offers must not set max_concurrent.'})


class OfferPoolItem(models.Model):
    """An OwnedProduct queued in a pool, waiting to be pushed to the offer."""

    pool = models.ForeignKey(
        OfferPool,
        on_delete=models.PROTECT,
        related_name='items',
    )
    owned_product = models.ForeignKey(
        'inventory.OwnedProduct',
        on_delete=models.PROTECT,
        related_name='pool_items',
    )
    pool_offer = models.ForeignKey(
        PoolOffer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='items',
    )
    reservation = models.ForeignKey(
        'posting.PoolDispatchReservation',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='items',
    )
    status = models.CharField(
        max_length=10,
        choices=OfferPoolItemStatus.choices,
        default=OfferPoolItemStatus.PENDING,
    )
    pushed_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    target_offer_id = models.CharField(
        max_length=255, blank=True,
        help_text='Remote offer ID this credential was pushed to (relevant for PA clones)',
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text='Push priority (lower = pushed first)',
    )
    remote_credential_id = models.CharField(max_length=255, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, unique=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    failure_stage = models.CharField(max_length=30, blank=True)
    remote_state = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'offer_pool_items'
        ordering = ['order', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['pool', 'owned_product'],
                name='unique_pool_owned_product',
            ),
            models.UniqueConstraint(
                fields=['owned_product'],
                name='unique_owned_product_across_pools',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=OfferPoolItemStatus.PENDING)
                    | models.Q(pool_offer__isnull=True, reservation__isnull=True)
                ),
                name='pending_item_unassigned',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=OfferPoolItemStatus.RESERVED)
                    | models.Q(pool_offer__isnull=True)
                ),
                name='reserved_item_no_pool_offer',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=OfferPoolItemStatus.RESERVED)
                    | models.Q(reservation__isnull=False)
                ),
                name='reserved_item_has_reservation',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status__in=[
                        OfferPoolItemStatus.QUEUED,
                        OfferPoolItemStatus.PUSHED,
                        OfferPoolItemStatus.CONSUMED,
                    ])
                    | models.Q(pool_offer__isnull=False)
                ),
                name='assigned_pool_item_has_offer',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=OfferPoolItemStatus.QUEUED)
                    | models.Q(claim_token__isnull=False)
                ),
                name='queued_pool_item_has_claim',
            ),
        ]
        indexes = [
            models.Index(fields=['pool', 'status']),
            models.Index(
                fields=['pool', 'status', 'pool_offer', 'order'],
                name='pool_item_claim_idx',
            ),
            models.Index(
                fields=['pool_offer', 'status'],
                name='pool_item_offer_status_idx',
            ),
            models.Index(
                fields=['reservation', 'pool', 'status'],
                name='pool_item_reservation_idx',
            ),
        ]

    def __str__(self):
        return f"PoolItem #{self.pk} — {self.owned_product.login} ({self.status})"


class OfferPoolActiveOffer(models.Model):
    """PA clone strategy: tracks individual cloned offers spawned from a pool."""

    pool = models.ForeignKey(
        OfferPool,
        on_delete=models.PROTECT,
        related_name='active_offers',
        help_text='Deprecated: derive through pool_offer.pool',
    )
    pool_offer = models.ForeignKey(
        PoolOffer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='active_offers',
    )
    store_listing_id = models.CharField(
        max_length=255,
        help_text='Remote offer ID on the marketplace',
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='pool_active_offers',
    )
    pool_item = models.ForeignKey(
        OfferPoolItem,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='active_offers',
        help_text='Which pool item (credential) was used for this offer',
    )
    status = models.CharField(
        max_length=10,
        choices=OfferPoolActiveOfferStatus.choices,
        default=OfferPoolActiveOfferStatus.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'offer_pool_active_offers'
        indexes = [
            models.Index(fields=['pool', 'status']),
            models.Index(
                fields=['pool_offer', 'status'],
                name='pool_active_offer_status_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['pool_offer', 'store_listing_id'],
                name='unique_pool_offer_remote_clone',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=OfferPoolActiveOfferStatus.ACTIVE)
                    | (
                        models.Q(listing__isnull=False)
                        & models.Q(pool_item__isnull=False)
                    )
                ),
                name='active_clone_requires_listing_item',
            ),
        ]

    def __str__(self):
        return f"ActiveOffer #{self.pk} — {self.store_listing_id} ({self.status})"


class PoolDispatchOperation(models.TextChoices):
    PUSH = 'push', 'Push'
    REMOVE = 'remove', 'Remove'
    RECONCILE = 'reconcile', 'Reconcile'


class PoolDispatchStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    IN_PROGRESS = 'in_progress', 'In Progress'
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'
    UNKNOWN = 'unknown', 'Unknown Remote Outcome'
    ROLLED_BACK = 'rolled_back', 'Rolled Back'


class PoolDispatchAttempt(models.Model):
    """Durable record for an idempotent remote pool mutation."""

    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    item = models.ForeignKey(
        OfferPoolItem,
        on_delete=models.PROTECT,
        related_name='dispatch_attempts',
    )
    pool_offer = models.ForeignKey(
        PoolOffer,
        on_delete=models.PROTECT,
        related_name='dispatch_attempts',
    )
    operation = models.CharField(max_length=16, choices=PoolDispatchOperation.choices)
    status = models.CharField(
        max_length=16,
        choices=PoolDispatchStatus.choices,
        default=PoolDispatchStatus.PENDING,
    )
    remote_offer_id = models.CharField(max_length=255, blank=True)
    remote_credential_id = models.CharField(max_length=255, blank=True)
    request_fingerprint = models.CharField(max_length=64)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pool_dispatch_attempts'
        indexes = [
            models.Index(
                fields=['pool_offer', 'status'],
                name='pool_attempt_offer_status_idx',
            ),
            models.Index(
                fields=['item', '-created_at'],
                name='pool_attempt_item_created_idx',
            ),
        ]


class PoolDispatchReservationStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    FINALIZED = 'finalized', 'Finalized'
    RELEASED = 'released', 'Released'
    FAILED = 'failed', 'Failed'


class PoolDispatchReservation(models.Model):
    """Group-level reservation for creating a brand-new PoolOffer from a pool.

    Holds RESERVED OfferPoolItems together under a single dispatch operation.
    ``token`` is the group-level idempotency key (distinct from per-item claim_token).
    """

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    pool = models.ForeignKey(
        OfferPool,
        on_delete=models.PROTECT,
        related_name='dispatch_reservations',
    )
    store = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.PROTECT,
        related_name='pool_dispatch_reservations',
    )
    job = models.OneToOneField(
        PostingJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='pool_dispatch_reservation',
    )
    status = models.CharField(
        max_length=16,
        choices=PoolDispatchReservationStatus.choices,
        default=PoolDispatchReservationStatus.ACTIVE,
    )
    item_count = models.PositiveIntegerField(default=0)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'pool_dispatch_reservations'
        indexes = [
            models.Index(
                fields=['pool', 'status'],
                name='dispatch_res_pool_status_idx',
            ),
            models.Index(
                fields=['status', 'created_at'],
                name='dispatch_res_stale_idx',
            ),
        ]

    def __str__(self):
        return f"Reservation #{self.pk} — {self.pool} ({self.status})"


class PoolSaleEvent(models.Model):
    """Deduplicates sale notifications before local counters are changed."""

    event_key = models.CharField(max_length=255, unique=True)
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.PROTECT,
        related_name='pool_sale_events',
    )
    pool_offer = models.ForeignKey(
        PoolOffer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sale_events',
    )
    order_id = models.BigIntegerField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pool_sale_events'
        indexes = [
            models.Index(
                fields=['pool_offer', '-created_at'],
                name='pool_sale_offer_created_idx',
            ),
        ]
