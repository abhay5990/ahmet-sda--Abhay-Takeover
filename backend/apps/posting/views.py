import json

from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount
from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct, Game
from apps.listings.models import Listing
from apps.posting.models import (
    ContentTemplate,
    DropshippingJobConfig, OfferPool, PostingJob, PostingLog,
)
from apps.posting.services.shared.subplatform import GAME_SUBPLATFORMS
from payload_pipeline.core.enums import GameSlug

SUPPORTED_GAME_SLUGS = {gs.value for gs in GameSlug}


# ── Stock Posting ──────────────────────────────────────────────────

@ensure_csrf_cookie
@role_required('admin', 'user')
def stock_start_page(request):
    """Job creation form."""
    games = Game.objects.filter(is_active=True, slug__in=SUPPORTED_GAME_SLUGS).order_by('name')
    stores = IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).order_by('provider', 'name')
    source_accounts = IntegrationAccount.objects.filter(
        provider='lzt', is_active=True,
    ).order_by('name')
    return render(request, 'posting/stock_start.html', {
        'games': games,
        'stores': stores,
        'source_accounts': source_accounts,
        'game_subplatforms_json': json.dumps(GAME_SUBPLATFORMS),
    })


@role_required('admin', 'user')
def stock_active_page(request):
    """Running/pending job list with live SSE progress."""
    active_jobs = PostingJob.objects.filter(
        status__in=['pending', 'running'],
    ).select_related('game').order_by('-created_at')
    return render(request, 'posting/stock_active.html', {
        'active_jobs': active_jobs,
    })


@role_required('admin', 'user')
def stock_history_page(request):
    """Completed/failed/cancelled jobs — filterable."""
    jobs = PostingJob.objects.filter(
        status__in=['completed', 'failed', 'cancelled'],
    ).select_related('game').order_by('-created_at')

    # Filters
    status = request.GET.get('status')
    if status in ('completed', 'failed', 'cancelled'):
        jobs = jobs.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        jobs = jobs.filter(game_id=game_id)

    paginator = Paginator(jobs, 50)
    page = paginator.get_page(request.GET.get('page'))

    games = Game.objects.filter(is_active=True).order_by('name')
    return render(request, 'posting/stock_history.html', {
        'jobs': page,
        'games': games,
        'selected_status': status or '',
        'selected_game': game_id or '',
    })


@role_required('admin', 'user')
def stock_job_detail(request, job_id):
    """Job detail — items table + live SSE updates."""
    job = get_object_or_404(PostingJob.objects.select_related('game'), id=job_id)
    items = job.items.select_related('owned_product', 'store', 'listing').order_by('id')
    return render(request, 'posting/stock_job_detail.html', {
        'job': job,
        'items': items,
    })


@ensure_csrf_cookie
@role_required('admin', 'user')
def content_templates_page(request):
    """Manage content templates with {field_name} placeholders."""
    games = Game.objects.filter(is_active=True).order_by('name')
    game_options = [
        {'id': game.id, 'name': game.name, 'slug': game.slug}
        for game in games
    ]
    return render(request, 'posting/content_templates.html', {
        'games': games,
        'game_options_json': json.dumps(game_options),
        'marketplace_options_json': json.dumps(ContentTemplate.MARKETPLACE_CHOICES),
        'template_type_options_json': json.dumps(ContentTemplate.TEMPLATE_TYPE_CHOICES),
    })


# ── Dropship Posting ──────────────────────────────────────────────

@role_required('admin', 'user')
def dropship_configs_page(request):
    """Config management + Run Now."""
    games = Game.objects.filter(is_active=True, slug__in=SUPPORTED_GAME_SLUGS).order_by('name')
    source_accounts = IntegrationAccount.objects.filter(
        is_active=True, provider='lzt',
    ).order_by('name')
    target_stores = IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).order_by('provider', 'name')
    configs = (
        DropshippingJobConfig.objects
        .select_related('source_account', 'store', 'game')
        .prefetch_related('target_urls')
        .order_by('-created_at')
    )
    return render(request, 'posting/dropship_configs.html', {
        'games': games,
        'source_accounts': source_accounts,
        'target_stores': target_stores,
        'configs': configs,
    })


@role_required('admin', 'user')
def dropship_items_page(request):
    """Posted dropship items — filterable table with pagination."""
    qs = (
        DropshipProduct.objects
        .select_related('source_account', 'game')
        .prefetch_related(
            Prefetch(
                'listings',
                queryset=Listing.objects.select_related('integration_account')
                    .order_by('-created_at'),
            ),
        )
        .order_by('-created_at')
    )

    # Filters
    status = request.GET.get('status')
    if status in DropshipProductStatus.values:
        qs = qs.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        qs = qs.filter(game_id=game_id)

    source_id = request.GET.get('source')
    if source_id:
        qs = qs.filter(source_account_id=source_id)

    store_id = request.GET.get('store')
    if store_id:
        qs = qs.filter(listings__integration_account_id=store_id).distinct()

    q = request.GET.get('q', '').strip()
    if q:
        if q.isdigit():
            qs = qs.filter(
                Q(product_title__icontains=q) | Q(source_product_id=int(q))
            )
        else:
            qs = qs.filter(product_title__icontains=q)

    # Stats (global)
    _all_counts = dict(
        DropshipProduct.objects.order_by()
        .values('status').annotate(n=Count('id')).values_list('status', 'n')
    )
    stats_items = [
        {'label': 'Listed', 'value': _all_counts.get(DropshipProductStatus.LISTED, 0), 'color': 'blue'},
        {'label': 'Sold', 'value': _all_counts.get(DropshipProductStatus.SOLD, 0), 'color': 'emerald'},
        {'label': 'Deleted', 'value': _all_counts.get(DropshipProductStatus.DELETED, 0), 'color': 'red'},
    ]

    # Pagination
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Filter options
    games = Game.objects.filter(is_active=True).order_by('name')
    sources = IntegrationAccount.objects.filter(
        provider='lzt', is_active=True,
    ).order_by('name')
    stores = IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).order_by('provider', 'name')

    return render(request, 'posting/dropship_items.html', {
        'page_obj': page_obj,
        'stats_items': stats_items,
        'item_statuses': [('listed', 'Listed'), ('sold', 'Sold'), ('deleted', 'Deleted')],
        'games': games,
        'sources': sources,
        'stores': stores,
        'selected_status': status or '',
        'selected_game': game_id or '',
        'selected_source': source_id or '',
        'selected_store': store_id or '',
        'q': q,
    })


@role_required('admin', 'user')
def dropship_activity_page(request):
    """Dropship log table with filters."""
    logs = PostingLog.objects.filter(
        task_name__in=['dropship_poster', 'dropship_cleaner'],
    ).order_by('-created_at')

    # Filters
    level = request.GET.get('level')
    if level in ('info', 'warning', 'error', 'success'):
        logs = logs.filter(level=level)

    config_id = request.GET.get('config')
    if config_id:
        logs = logs.filter(detail__config_id=int(config_id))

    paginator = Paginator(logs, 100)
    page = paginator.get_page(request.GET.get('page'))

    configs = DropshippingJobConfig.objects.select_related('store', 'source_account')
    return render(request, 'posting/dropship_activity.html', {
        'logs': page,
        'configs': configs,
        'selected_level': level or '',
        'selected_config': config_id or '',
    })


# ── Auto Restock (Offer Pools) ───────────────────────────────────

@ensure_csrf_cookie
@role_required('admin', 'user')
def restock_pools_page(request):
    """Offer pool list + creation form."""
    pools = (
        OfferPool.objects
        .select_related('listing', 'game', 'store')
        .order_by('-created_at')
    )
    games = Game.objects.filter(is_active=True).order_by('name')
    stores = IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).order_by('provider', 'name')
    return render(request, 'posting/restock_pools.html', {
        'pools': pools,
        'games': games,
        'stores': stores,
    })


@ensure_csrf_cookie
@role_required('admin', 'user')
def restock_pool_detail_page(request, pool_id):
    """Pool detail — items, active offers, logs."""
    pool = get_object_or_404(
        OfferPool.objects.select_related('listing', 'game', 'store'),
        id=pool_id,
    )
    items = pool.items.select_related('owned_product').order_by('order', 'created_at')
    active_offers = pool.active_offers.select_related('listing', 'pool_item').order_by('-created_at')

    # Linked OwnedProducts via ListingOwnedProduct M2M
    from apps.listings.models import ListingOwnedProduct
    linked_accounts = (
        ListingOwnedProduct.objects
        .filter(listing=pool.listing)
        .select_related('owned_product')
        .order_by('created_at')
    )

    logs = PostingLog.objects.filter(
        task_name__in=['pool_replenish', 'pool_checker'],
        detail__pool_id=pool.pk,
    ).order_by('-created_at')[:50]

    return render(request, 'posting/restock_pool_detail.html', {
        'pool': pool,
        'items': items,
        'active_offers': active_offers,
        'linked_accounts': linked_accounts,
        'logs': logs,
    })
