from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import IntegrationAccount, AccountGroup, IntegrationCredential, Proxy
from .providers.registry import get_credential_fields


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
            return format_html('<span style="color: gray;">N/A</span>')
        if obj.is_token_expired:
            return format_html('<span style="color: red;">Expired</span>')
        return format_html('<span style="color: green;">Valid</span>')
