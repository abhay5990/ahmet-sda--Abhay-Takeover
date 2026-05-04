from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.integrations.models import AccountGroup
from apps.inventory.models import Category, Game

from .forms import AccountGroupForm


class GroupListView(LoginRequiredMixin, ListView):
    model = AccountGroup
    template_name = 'settings/group_list.html'
    context_object_name = 'groups'

    def get_queryset(self):
        return AccountGroup.objects.prefetch_related('accounts', 'proxies').all()


class GroupCreateView(LoginRequiredMixin, View):
    def get(self, request):
        form = AccountGroupForm()
        return render(request, 'settings/group_form.html', {'form': form, 'is_edit': False})

    def post(self, request):
        form = AccountGroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            messages.success(request, f'Group "{group.name}" created.')
            return redirect('settings:group_list')
        return render(request, 'settings/group_form.html', {'form': form, 'is_edit': False})


class GroupEditView(LoginRequiredMixin, View):
    def get(self, request, pk):
        group = get_object_or_404(AccountGroup, pk=pk)
        form = AccountGroupForm(instance=group)
        return render(request, 'settings/group_form.html', {'form': form, 'is_edit': True, 'group': group})

    def post(self, request, pk):
        group = get_object_or_404(AccountGroup, pk=pk)
        form = AccountGroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, f'Group "{group.name}" updated.')
            return redirect('settings:group_list')
        return render(request, 'settings/group_form.html', {'form': form, 'is_edit': True, 'group': group})


class GroupDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(AccountGroup, pk=pk)
        name = group.name
        group.delete()
        messages.success(request, f'Group "{name}" deleted.')
        return redirect('settings:group_list')


class GameListView(LoginRequiredMixin, ListView):
    model = Game
    template_name = 'settings/game_list.html'
    context_object_name = 'games'

    def get_queryset(self):
        qs = Game.objects.select_related('category').prefetch_related('platform_mappings')
        category_id = self.request.GET.get('category')
        if category_id:
            qs = qs.filter(category_id=category_id)
        search = self.request.GET.get('q')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categories'] = Category.objects.all()
        ctx['selected_category'] = self.request.GET.get('category', '')
        ctx['search_query'] = self.request.GET.get('q', '')
        return ctx
