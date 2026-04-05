from django import forms
from django.utils.text import slugify

from .models import IntegrationAccount, IntegrationCredential
from .providers.registry import get_credential_fields

TAILWIND_INPUT = 'w-full rounded-md border-gray-300 shadow-sm focus:border-emerald-500 focus:ring-emerald-500 text-sm'
TAILWIND_SELECT = TAILWIND_INPUT
TAILWIND_TEXTAREA = TAILWIND_INPUT
TAILWIND_CHECKBOX = 'rounded border-gray-300 text-emerald-600 focus:ring-emerald-500'


class AccountForm(forms.ModelForm):
    class Meta:
        model = IntegrationAccount
        fields = ('name', 'provider', 'role', 'group', 'is_active', 'notes')
        widgets = {
            'name': forms.TextInput(attrs={'class': TAILWIND_INPUT}),
            'provider': forms.Select(attrs={'class': TAILWIND_SELECT}),
            'role': forms.Select(attrs={'class': TAILWIND_SELECT}),
            'group': forms.Select(attrs={'class': TAILWIND_SELECT}),
            'is_active': forms.CheckboxInput(attrs={'class': TAILWIND_CHECKBOX}),
            'notes': forms.Textarea(attrs={'class': TAILWIND_TEXTAREA, 'rows': 3}),
        }

    def __init__(self, *args, is_edit=False, **kwargs):
        super().__init__(*args, **kwargs)
        if is_edit:
            self.fields['provider'].disabled = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.slug:
            base_slug = slugify(f"{instance.provider}-{instance.name}")
            slug = base_slug
            counter = 2
            while IntegrationAccount.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            instance.slug = slug
        if commit:
            instance.save()
        return instance


class CredentialForm(forms.Form):
    def __init__(self, *args, provider=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.provider = provider
        if not provider:
            return

        credential_fields = get_credential_fields(provider)
        existing_creds = {}
        if instance and instance.pk:
            existing_creds = instance.credentials or {}

        for field_def in credential_fields:
            field_name = f'cred_{field_def.name}'
            if field_def.read_only:
                self.fields[field_name] = forms.CharField(
                    label=field_def.label,
                    required=False,
                    initial=existing_creds.get(field_def.name, ''),
                    help_text=field_def.help_text,
                    widget=forms.TextInput(attrs={
                        'class': TAILWIND_INPUT,
                        'readonly': 'readonly',
                        'tabindex': '-1',
                    }),
                )
            elif field_def.field_type == 'password':
                is_existing = instance and instance.pk
                self.fields[field_name] = forms.CharField(
                    label=field_def.label,
                    required=field_def.required and not is_existing,
                    initial='',
                    help_text=field_def.help_text or ('Leave blank to keep current value' if is_existing else ''),
                    widget=forms.PasswordInput(attrs={
                        'class': TAILWIND_INPUT,
                        'autocomplete': 'off',
                    }),
                )
            else:
                self.fields[field_name] = forms.CharField(
                    label=field_def.label,
                    required=field_def.required and not (instance and instance.pk),
                    initial=existing_creds.get(field_def.name, ''),
                    help_text=field_def.help_text,
                    widget=forms.TextInput(attrs={'class': TAILWIND_INPUT}),
                )

    def save(self, account):
        credential, created = IntegrationCredential.objects.get_or_create(
            account=account,
            defaults={'credentials': {}},
        )
        credential_fields = get_credential_fields(self.provider)
        existing_creds = credential.credentials.copy() if credential.credentials else {}

        for field_def in credential_fields:
            if field_def.read_only:
                continue
            value = self.cleaned_data.get(f'cred_{field_def.name}', '')
            if field_def.field_type == 'password' and not value:
                continue
            if value:
                existing_creds[field_def.name] = value

        credential.credentials = existing_creds
        credential.save()
        return credential
