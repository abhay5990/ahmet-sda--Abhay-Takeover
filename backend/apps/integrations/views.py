from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import AccountForm, CredentialForm, ServiceCredentialForm
from .models import IntegrationAccount, ServiceCredential
from .providers.registry import get_provider
from .services.registry import get_service, get_service_fields


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


# ---------------------------------------------------------------------------
# Service Credential views
# ---------------------------------------------------------------------------

class ServiceListView(LoginRequiredMixin, ListView):
    model = ServiceCredential
    template_name = 'integrations/service_list.html'
    context_object_name = 'services'


class ServiceCreateView(LoginRequiredMixin, View):
    def get(self, request):
        form = ServiceCredentialForm()
        return render(request, 'integrations/service_form.html', {'form': form, 'is_edit': False})

    def post(self, request):
        form = ServiceCredentialForm(request.POST)
        if form.is_valid():
            service = form.save()
            messages.success(request, f'Service "{service.name}" created successfully.')
            return redirect('settings:service_detail', slug=service.slug)
        return render(request, 'integrations/service_form.html', {'form': form, 'is_edit': False})


class ServiceUpdateView(LoginRequiredMixin, View):
    def get(self, request, slug):
        service = get_object_or_404(ServiceCredential, slug=slug)
        form = ServiceCredentialForm(instance=service, is_edit=True)
        return render(request, 'integrations/service_form.html', {
            'form': form, 'is_edit': True, 'service': service,
        })

    def post(self, request, slug):
        service = get_object_or_404(ServiceCredential, slug=slug)
        form = ServiceCredentialForm(request.POST, instance=service, is_edit=True)
        if form.is_valid():
            form.save()
            messages.success(request, f'Service "{service.name}" updated successfully.')
            return redirect('settings:service_detail', slug=service.slug)
        return render(request, 'integrations/service_form.html', {
            'form': form, 'is_edit': True, 'service': service,
        })


class ServiceDeleteView(LoginRequiredMixin, View):
    def post(self, request, slug):
        service = get_object_or_404(ServiceCredential, slug=slug)
        name = service.name
        service.delete()
        messages.success(request, f'Service "{name}" deleted successfully.')
        return redirect('settings:service_list')


class ServiceDetailView(LoginRequiredMixin, DetailView):
    model = ServiceCredential
    template_name = 'integrations/service_detail.html'
    context_object_name = 'service'
    slug_field = 'slug'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        service = self.object
        cred_fields = get_service_fields(service.service_type)
        existing_creds = service.credentials or {}
        ctx['cred_status'] = [
            {
                'label': f.label,
                'is_set': bool(existing_creds.get(f.name)),
                'is_password': f.field_type == 'password',
            }
            for f in cred_fields
        ]
        return ctx


class ServiceFieldsView(LoginRequiredMixin, View):
    """AJAX endpoint: returns rendered credential fields for a given service_type."""
    def get(self, request, service_type):
        form = ServiceCredentialForm(data={'service_type': service_type})
        # Build a list of only the cred_* fields for the partial template
        cred_form = [field for field in form if field.name.startswith('cred_')]
        html = render_to_string(
            'integrations/_service_credential_fields.html',
            {'cred_form': cred_form},
            request=request,
        )
        return JsonResponse({'html': html})


class ServiceTestView(LoginRequiredMixin, View):
    def post(self, request, slug):
        service = get_object_or_404(ServiceCredential, slug=slug)
        svc = get_service(service.service_type)
        if svc is None:
            return JsonResponse({'status': 'error', 'message': 'No service handler registered for this type.'}, status=400)
        if not hasattr(svc, 'build_client'):
            return JsonResponse({'status': 'error', 'message': 'This service does not support connection testing yet.'}, status=400)
        try:
            client = svc.build_client(service)
            success, message = svc.test_connection(client)
            if success:
                return JsonResponse({'status': 'ok', 'message': message})
            return JsonResponse({'status': 'error', 'message': message}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
