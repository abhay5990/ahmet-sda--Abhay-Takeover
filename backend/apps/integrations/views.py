from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import AccountForm, CredentialForm
from .models import IntegrationAccount
from .providers.registry import get_provider


class AccountListView(LoginRequiredMixin, ListView):
    model = IntegrationAccount
    template_name = 'integrations/account_list.html'
    context_object_name = 'accounts'

    def get_queryset(self):
        return IntegrationAccount.objects.select_related('group', 'credential').all()


class AccountCreateView(LoginRequiredMixin, View):
    def get(self, request):
        form = AccountForm()
        cred_form = CredentialForm()
        return render(request, 'integrations/account_form.html', {
            'form': form,
            'cred_form': cred_form,
            'is_edit': False,
        })

    def post(self, request):
        form = AccountForm(request.POST)
        provider = request.POST.get('provider', '')
        cred_form = CredentialForm(request.POST, provider=provider)

        if form.is_valid() and cred_form.is_valid():
            account = form.save()
            cred_form.save(account)
            messages.success(request, f'Account "{account.name}" created successfully.')
            return redirect('integrations:account_detail', slug=account.slug)

        return render(request, 'integrations/account_form.html', {
            'form': form,
            'cred_form': cred_form,
            'is_edit': False,
        })


class AccountUpdateView(LoginRequiredMixin, View):
    def get(self, request, slug):
        account = get_object_or_404(IntegrationAccount, slug=slug)
        credential = getattr(account, 'credential', None)
        form = AccountForm(instance=account, is_edit=True)
        cred_form = CredentialForm(provider=account.provider, instance=credential)
        return render(request, 'integrations/account_form.html', {
            'form': form,
            'cred_form': cred_form,
            'is_edit': True,
            'account': account,
        })

    def post(self, request, slug):
        account = get_object_or_404(IntegrationAccount, slug=slug)
        credential = getattr(account, 'credential', None)
        form = AccountForm(request.POST, instance=account, is_edit=True)
        cred_form = CredentialForm(request.POST, provider=account.provider, instance=credential)

        if form.is_valid() and cred_form.is_valid():
            account = form.save()
            cred_form.save(account)
            messages.success(request, f'Account "{account.name}" updated successfully.')
            return redirect('integrations:account_detail', slug=account.slug)

        return render(request, 'integrations/account_form.html', {
            'form': form,
            'cred_form': cred_form,
            'is_edit': True,
            'account': account,
        })


class AccountDeleteView(LoginRequiredMixin, View):
    def post(self, request, slug):
        account = get_object_or_404(IntegrationAccount, slug=slug)
        name = account.name
        account.delete()
        messages.success(request, f'Account "{name}" deleted successfully.')
        return redirect('integrations:account_list')


class AccountDetailView(LoginRequiredMixin, DetailView):
    model = IntegrationAccount
    template_name = 'integrations/account_detail.html'
    context_object_name = 'account'
    slug_field = 'slug'

    def get_queryset(self):
        return IntegrationAccount.objects.select_related('group', 'credential').all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        account = self.object
        credential = getattr(account, 'credential', None)
        from .providers.registry import get_credential_fields
        cred_fields = get_credential_fields(account.provider)
        cred_status = []
        existing_creds = credential.credentials if credential and credential.credentials else {}
        for f in cred_fields:
            cred_status.append({
                'label': f.label,
                'is_set': bool(existing_creds.get(f.name)),
                'is_password': f.field_type == 'password',
            })
        ctx['credential'] = credential
        ctx['cred_status'] = cred_status
        return ctx


class CredentialFieldsView(LoginRequiredMixin, View):
    """AJAX endpoint: returns rendered credential fields for a given provider."""
    def get(self, request, provider):
        cred_form = CredentialForm(provider=provider)
        html = render_to_string('integrations/_credential_fields.html', {'cred_form': cred_form}, request=request)
        return JsonResponse({'html': html})


class TestConnectionView(LoginRequiredMixin, View):
    def post(self, request, slug):
        account = get_object_or_404(
            IntegrationAccount.objects.select_related('credential'),
            slug=slug,
        )
        credential = getattr(account, 'credential', None)
        if not credential:
            return JsonResponse({'status': 'error', 'message': 'No credentials configured.'}, status=400)

        try:
            provider = get_provider(account.provider)
            client = provider.build_client(credential)
            provider.fetch_products(client)
            return JsonResponse({'status': 'ok', 'message': 'Connection successful!'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
