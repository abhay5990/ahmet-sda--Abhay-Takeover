from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.encryption import EncryptedJSONField


class Provider(models.TextChoices):
    LZT = 'lzt', 'LZT Market'
    G2G = 'g2g', 'G2G'
    ELDORADO = 'eldorado', 'Eldorado'
    GAMEBOOST = 'gameboost', 'Gameboost'
    PLAYERAUCTIONS = 'playerauctions', 'PlayerAuctions'


class AccountGroup(models.Model):
    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'account_groups'
        ordering = ['name']

    def __str__(self):
        return self.name


class IntegrationAccount(models.Model):
    class Role(models.TextChoices):
        BUY = 'buy', 'Buy (Source)'
        SELL = 'sell', 'Sell (Target)'
        BOTH = 'both', 'Both'

    name = models.CharField(max_length=100, help_text='Account name, e.g. "store4gamers"')
    provider = models.CharField(
        max_length=50,
        choices=Provider.choices,
        help_text='Which marketplace provider this account uses',
    )
    slug = models.SlugField(unique=True, help_text='e.g. "eldorado-store4gamers"')
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.SELL,
    )
    group = models.ForeignKey(
        AccountGroup,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='accounts',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integration_accounts'
        ordering = ['provider', 'name']

    def clean(self):
        if self.group_id:
            conflict = IntegrationAccount.objects.filter(
                group=self.group,
                provider=self.provider,
            ).exclude(pk=self.pk)
            if conflict.exists():
                raise ValidationError(
                    f'Group "{self.group}" already has an account for provider "{self.get_provider_display()}".'
                )

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"


class IntegrationCredential(models.Model):
    account = models.OneToOneField(
        IntegrationAccount,
        on_delete=models.CASCADE,
        related_name='credential',
    )
    credentials = EncryptedJSONField(
        default=dict,
        help_text='Provider-specific credentials (encrypted at rest)',
    )
    token_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the current access token expires (for OAuth/session-based providers)',
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integration_credentials'

    def __str__(self):
        return f"Credentials for {self.account.name}"

    @property
    def is_token_expired(self):
        if self.token_expires_at is None:
            return False
        return timezone.now() >= self.token_expires_at

    def update_token(self, access_token, expires_at=None, **extra):
        """Update access token after refresh. Merges extra fields into credentials."""
        creds = self.credentials.copy()
        creds['access_token'] = access_token
        creds.update(extra)
        self.credentials = creds
        self.token_expires_at = expires_at
        self.save(update_fields=['credentials', 'token_expires_at', 'updated_at'])


class ServiceType(models.TextChoices):
    PROXY         = 'proxy',         'Proxy Provider'
    IMAGE         = 'image',         'Image Hosting'
    STORAGE       = 'storage',       'Cloud Storage'
    GAME          = 'game-service',  'Game Service'
    NOTIFICATION  = 'notification',  'Notification Service'
    OTHER         = 'other',         'Other'


class ServiceCredential(models.Model):
    """Encrypted credential storage for non-marketplace external services.

    Examples: Proxyline (proxy provider), RobuxCrate (game service),
    Imgur/ImageShack (image hosting), Dropbox (cloud storage).

    Unlike IntegrationCredential, this model has no account/role/group concept.
    Each service type defines its own field schema via integrations/services/ registry.
    Adding a new service type requires no migration — only a new Python file.
    """

    name         = models.CharField(max_length=100, help_text='e.g. "Proxyline Main", "Imgur Production"')
    service_type = models.CharField(max_length=50, choices=ServiceType.choices)
    slug         = models.SlugField(unique=True, help_text='e.g. "proxyline-main", "imgur-prod"')
    credentials  = EncryptedJSONField(default=dict, help_text='Service-specific credentials (encrypted at rest)')
    base_url     = models.URLField(blank=True, help_text='Optional: override default API endpoint')
    is_active    = models.BooleanField(default=True)
    notes        = models.TextField(blank=True)

    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_credentials'
        ordering = ['service_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_service_type_display()})"


class Proxy(models.Model):
    """Proxy assigned to an AccountGroup for IP isolation."""

    group = models.ForeignKey(
        AccountGroup,
        on_delete=models.CASCADE,
        related_name='proxies',
    )
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField()
    username = models.CharField(max_length=255, blank=True)
    password = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'proxies'
        ordering = ['group', 'host']
        verbose_name_plural = 'proxies'

    def __str__(self):
        label = f"{self.host}:{self.port}"
        if self.username:
            label += f" ({self.username})"
        return label

    def to_proxy_string(self) -> str:
        """Format as host:port:user:pass for PA token service."""
        if self.username and self.password:
            return f"{self.host}:{self.port}:{self.username}:{self.password}"
        return f"{self.host}:{self.port}"
