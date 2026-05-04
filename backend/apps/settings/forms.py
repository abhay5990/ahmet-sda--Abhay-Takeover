from django import forms

from apps.integrations.models import AccountGroup, Proxy

TAILWIND_INPUT = 'w-full rounded-md border-gray-300 shadow-sm focus:border-emerald-500 focus:ring-emerald-500 text-sm'


class AccountGroupForm(forms.ModelForm):
    proxies_text = forms.CharField(
        label='Proxies',
        required=False,
        widget=forms.Textarea(attrs={
            'class': TAILWIND_INPUT,
            'rows': 6,
            'placeholder': 'host:port:username:password\nhost:port:username:password\n...',
        }),
        help_text='One proxy per line. Format: host:port:username:password',
    )

    class Meta:
        model = AccountGroup
        fields = ('name', 'notes')
        widgets = {
            'name': forms.TextInput(attrs={'class': TAILWIND_INPUT}),
            'notes': forms.Textarea(attrs={'class': TAILWIND_INPUT, 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            lines = [
                p.to_proxy_string()
                for p in self.instance.proxies.all()
            ]
            self.fields['proxies_text'].initial = '\n'.join(lines)

    def clean_proxies_text(self):
        raw = self.cleaned_data.get('proxies_text', '').strip()
        if not raw:
            return []
        parsed = []
        for i, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            parts = line.split(':')
            if len(parts) < 2:
                raise forms.ValidationError(
                    f'Line {i}: Invalid format. Expected host:port or host:port:user:pass'
                )
            host = parts[0].strip()
            try:
                port = int(parts[1].strip())
            except ValueError:
                raise forms.ValidationError(f'Line {i}: Port must be a number.')
            username = parts[2].strip() if len(parts) > 2 else ''
            password = parts[3].strip() if len(parts) > 3 else ''
            parsed.append({'host': host, 'port': port, 'username': username, 'password': password})
        return parsed

    def save(self, commit=True):
        group = super().save(commit=commit)
        if commit:
            self._save_proxies(group)
        return group

    def _save_proxies(self, group):
        proxy_data = self.cleaned_data.get('proxies_text', [])
        group.proxies.all().delete()
        Proxy.objects.bulk_create([
            Proxy(group=group, **data) for data in proxy_data
        ])
