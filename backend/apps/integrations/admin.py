from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html, mark_safe

from .models import (
    IntegrationAccount, AccountGroup, IntegrationCredential,
    Proxy, ServiceCredential, TokenApiClient,
)
from .providers.registry import get_credential_fields
from .services.registry import get_service_fields


class IntegrationCredentialInlineForm(forms.ModelForm):
    """Dynamic form that renders provider-specific credential fields.

    Instead of showing a raw JSON textarea, it renders individual fields
    (api_key, username, password, etc.) based on the provider's credential schema.
    """

    class Meta:
        model = IntegrationCredential
        fields = ('is_active',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        provider = self._get_provider()
        if not provider:
            return

        credential_fields = get_credential_fields(provider)
        existing_creds = {}
        if self.instance and self.instance.pk:
            existing_creds = self.instance.credentials or {}

        for field_def in credential_fields:
            if field_def.read_only:
                self.fields[f'cred_{field_def.name}'] = forms.CharField(
                    label=field_def.label,
                    required=False,
                    initial=existing_creds.get(field_def.name, ''),
                    help_text=field_def.help_text,
                    widget=forms.TextInput(attrs={'readonly': 'readonly', 'class': 'vTextField'}),
                )
            elif field_def.field_type == 'password':
                self.fields[f'cred_{field_def.name}'] = forms.CharField(
                    label=field_def.label,
                    required=field_def.required and not self.instance.pk,
                    initial='',
                    help_text=field_def.help_text or ('Leave blank to keep current value' if self.instance.pk else ''),
                    widget=forms.PasswordInput(attrs={'class': 'vTextField', 'autocomplete': 'off'}),
                )
            else:
                self.fields[f'cred_{field_def.name}'] = forms.CharField(
                    label=field_def.label,
                    required=field_def.required and not self.instance.pk,
                    initial=existing_creds.get(field_def.name, ''),
                    help_text=field_def.help_text,
                    widget=forms.TextInput(attrs={'class': 'vTextField'}),
                )

    def _get_provider(self):
        # From existing instance
        if self.instance and self.instance.pk and self.instance.account_id:
            return self.instance.account.provider
        # From parent form data (when adding new)
        if self.data:
            return self.data.get('provider', '')
        return ''

    def save(self, commit=True):
        instance = super().save(commit=False)
        provider = self._get_provider()
        credential_fields = get_credential_fields(provider)

        existing_creds = instance.credentials.copy() if instance.credentials else {}

        for field_def in credential_fields:
            if field_def.read_only:
                continue
            value = self.cleaned_data.get(f'cred_{field_def.name}', '')
            if field_def.field_type == 'password' and not value:
                # Keep existing value for blank password fields
                continue
            if value:
                existing_creds[field_def.name] = value

        instance.credentials = existing_creds
        if commit:
            instance.save()
        return instance


class IntegrationCredentialInline(admin.StackedInline):
    model = IntegrationCredential
    form = IntegrationCredentialInlineForm
    can_delete = False
    max_num = 1
    extra = 0
    verbose_name = 'Credentials'
    verbose_name_plural = 'Credentials'

    def get_fields(self, request, obj=None):
        fields = ['is_active']
        if obj and obj.provider:
            credential_fields = get_credential_fields(obj.provider)
            for field_def in credential_fields:
                fields.append(f'cred_{field_def.name}')
        return fields


class ProxyInline(admin.TabularInline):
    model = Proxy
    extra = 1
    fields = ('host', 'port', 'username', 'password', 'is_active', 'notes')


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'proxy_count', 'created_at')
    inlines = [ProxyInline]

    @admin.display(description='Proxies')
    def proxy_count(self, obj):
        return obj.proxies.filter(is_active=True).count()


@admin.register(Proxy)
class ProxyAdmin(admin.ModelAdmin):
    list_display = ('host', 'port', 'username', 'group', 'is_active', 'created_at')
    list_filter = ('group', 'is_active')
    search_fields = ('host', 'username', 'notes')


@admin.register(IntegrationAccount)
class IntegrationAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider', 'slug', 'role', 'group', 'has_credentials', 'is_active', 'created_at')
    list_select_related = ('group',)
    list_filter = ('provider', 'role', 'group', 'is_active')
    prepopulated_fields = {'slug': ('provider', 'name')}
    inlines = [IntegrationCredentialInline]

    @admin.display(boolean=True, description='Creds')
    def has_credentials(self, obj):
        return hasattr(obj, 'credential') and obj.credential.is_active


class ServiceCredentialForm(forms.ModelForm):
    """Dynamic form that renders service-type-specific credential fields.

    Mirrors IntegrationCredentialInlineForm but for ServiceCredential (standalone).
    Field schema comes from integrations/services/ registry.
    """

    class Meta:
        model = ServiceCredential
        fields = ('name', 'service_type', 'slug', 'base_url', 'is_active', 'notes')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        service_type = self._get_service_type()
        if not service_type:
            return

        credential_fields = get_service_fields(service_type)
        existing_creds = {}
        if self.instance and self.instance.pk:
            existing_creds = self.instance.credentials or {}

        for field_def in credential_fields:
            if field_def.field_type == 'password':
                self.fields[f'cred_{field_def.name}'] = forms.CharField(
                    label=field_def.label,
                    required=field_def.required and not self.instance.pk,
                    initial='',
                    help_text=field_def.help_text or ('Leave blank to keep current value' if self.instance.pk else ''),
                    widget=forms.PasswordInput(attrs={'class': 'vTextField', 'autocomplete': 'off'}),
                )
            elif field_def.field_type == 'url':
                self.fields[f'cred_{field_def.name}'] = forms.URLField(
                    label=field_def.label,
                    required=False,
                    initial=existing_creds.get(field_def.name, ''),
                    help_text=field_def.help_text,
                    widget=forms.URLInput(attrs={'class': 'vTextField'}),
                )
            else:
                self.fields[f'cred_{field_def.name}'] = forms.CharField(
                    label=field_def.label,
                    required=field_def.required and not self.instance.pk,
                    initial=existing_creds.get(field_def.name, ''),
                    help_text=field_def.help_text,
                    widget=forms.TextInput(attrs={'class': 'vTextField'}),
                )

    def _get_service_type(self) -> str:
        if self.instance and self.instance.pk:
            return self.instance.service_type
        if self.data:
            return self.data.get('service_type', '')
        return ''

    def save(self, commit=True):
        instance = super().save(commit=False)
        service_type = instance.service_type
        credential_fields = get_service_fields(service_type)

        existing_creds = instance.credentials.copy() if instance.credentials else {}

        for field_def in credential_fields:
            value = self.cleaned_data.get(f'cred_{field_def.name}', '')
            if field_def.field_type == 'password' and not value:
                continue  # Keep existing value
            if value:
                existing_creds[field_def.name] = value

        instance.credentials = existing_creds
        if commit:
            instance.save()
        return instance


@admin.register(ServiceCredential)
class ServiceCredentialAdmin(admin.ModelAdmin):
    form = ServiceCredentialForm
    list_display  = ('name', 'service_type', 'slug', 'is_active', 'updated_at')
    list_filter   = ('service_type', 'is_active')
    search_fields = ('name', 'slug', 'notes')
    prepopulated_fields = {'slug': ('service_type', 'name')}
    readonly_fields = ('created_at', 'updated_at')

    def get_fields(self, request, obj=None):
        base = ['name', 'service_type', 'slug', 'base_url', 'is_active', 'notes']
        if obj and obj.service_type:
            credential_fields = get_service_fields(obj.service_type)
            base += [f'cred_{f.name}' for f in credential_fields]
        base += ['created_at', 'updated_at']
        return base


@admin.register(TokenApiClient)
class TokenApiClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_key_prefix', 'allow_any_ip', 'is_active', 'created_at')
    list_filter = ('is_active', 'allow_any_ip')
    search_fields = ('name', 'note')
    readonly_fields = ('api_key_prefix', 'api_key_hash', 'created_at')

    def get_fields(self, request, obj=None):
        if obj:
            # Editing existing: show read-only hash/prefix, no key generation
            return ['name', 'api_key_prefix', 'api_key_hash', 'allowed_ips', 'allow_any_ip', 'is_active', 'note', 'created_at']
        # Creating new: only editable fields (key auto-generated on save)
        return ['name', 'allowed_ips', 'allow_any_ip', 'is_active', 'note']

    def save_model(self, request, obj, form, change):
        if not change:
            # New client: generate API key
            import hashlib
            import secrets
            plain_key = secrets.token_urlsafe(32)
            obj.api_key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
            obj.api_key_prefix = plain_key[:8]
            obj.save()
            self.message_user(
                request,
                format_html(
                    '🔑 API key for <strong>{}</strong>: '
                    '<code style="user-select:all; background:#fff3cd; padding:4px 8px; '
                    'font-size:14px; border:1px solid #ffc107; border-radius:4px">{}</code> '
                    '— <strong>Copy now, it will NOT be shown again!</strong>',
                    obj.name, plain_key,
                ),
                messages.WARNING,
            )
        else:
            obj.save()


@admin.register(IntegrationCredential)
class IntegrationCredentialAdmin(admin.ModelAdmin):
    list_display = ('account', 'provider_display', 'is_active', 'token_status', 'updated_at')
    list_filter = ('is_active',)
    readonly_fields = ('account', 'token_expires_at', 'created_at', 'updated_at')

    @admin.display(description='Provider')
    def provider_display(self, obj):
        return obj.account.get_provider_display()

    @admin.display(description='Token Status')
    def token_status(self, obj):
        if obj.token_expires_at is None:
            return mark_safe('<span style="color: gray;">N/A</span>')
        if obj.is_token_expired:
            return mark_safe('<span style="color: red;">Expired</span>')
        return mark_safe('<span style="color: green;">Valid</span>')
