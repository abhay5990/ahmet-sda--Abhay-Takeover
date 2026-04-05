from django import forms

from apps.integrations.models import AccountGroup

TAILWIND_INPUT = 'w-full rounded-md border-gray-300 shadow-sm focus:border-emerald-500 focus:ring-emerald-500 text-sm'


class AccountGroupForm(forms.ModelForm):
    class Meta:
        model = AccountGroup
        fields = ('name', 'notes')
        widgets = {
            'name': forms.TextInput(attrs={'class': TAILWIND_INPUT}),
            'notes': forms.Textarea(attrs={'class': TAILWIND_INPUT, 'rows': 3}),
        }
