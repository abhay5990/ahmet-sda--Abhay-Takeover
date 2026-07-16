import json

from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q

from apps.accounts.decorators import role_required
from apps.integrations.models import IntegrationAccount
from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct, Game, GamePlatformMapping
from apps.listings.models import Listing
from apps.posting.models import (
    ContentTemplate, DropshippingJobConfig, OfferPool,
    OfferPoolActiveOffer, PoolOffer, PostingJob, PostingLog,
)
from apps.posting.models import GameVariant
from payload_pipeline.core.enums import GameSlug

SUPPORTED_GAME_SLUGS = {gs.value for gs in GameSlug}


def _get_game_providers() -> dict[str, list[str]]:
    """Return {game_id: [provider, ...]} from GamePlatformMapping."""
    result: dict[str, list[str]] = {}
    for m in GamePlatformMapping.objects.select_related('game').filter(
        game__is_active=True, game__slug__in=SUPPORTED_GAME_SLUGS,
    ):
        result.setdefault(str(m.game_id), []).append(m.platform)
    return result


def _get_game_variants() -> dict[str, list[str]]:
    """Return {game_slug: [variant_label, ...]} for UI platform selector."""
    result: dict[str, list[str]] = {}
    for v in GameVariant.objects.select_related('game').order_by('game__slug', 'type', 'sort_order'):
        result.setdefault(v.game.slug, []).append(v.label)
    return result


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
        'game_variants_json': json.dumps(_get_game_variants()),
        'game_providers_json': json.dumps(_get_game_providers()),
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
    """Job detail — grouped by login with per-marketplace status columns."""
    job = get_object_or_404(PostingJob.objects.select_related('game'), id=job_id)
    items = (
        job.items
        .select_related('owned_product', 'owned_product__category', 'store', 'listing')
        .order_by('id')
    )

    # Build login-grouped data for the template
    # Key by store_id (IntegrationAccount) so multiple stores on the same
    # marketplace each get their own column, e.g. "Eldorado (Store4Gamers)".
    from collections import OrderedDict
    grouped: OrderedDict[str, dict] = OrderedDict()
    job_stores: OrderedDict[str, str] = OrderedDict()  # store_id -> display

    MARKETPLACE_DISPLAY = {
        'eldorado': 'Eldorado', 'gameboost': 'GameBoost',
        'g2g': 'G2G', 'playerauctions': 'PlayerAuctions',
    }

    for item in items:
        store_key = str(item.store_id)
        mp_label = MARKETPLACE_DISPLAY.get(item.marketplace, item.marketplace)
        store_display = f"{mp_label} ({item.store.name})"
        job_stores[store_key] = store_display

        login = item.login
        if login not in grouped:
            op = item.owned_product
            grouped[login] = {
                'login': login,
                'ref_key': op.ref_key if op else '',
                'password': op.password if op else '',
                'email': op.email if op else '',
                'email_password': op.email_password if op else '',
                'purchase_price': str(op.price) if op and op.price else '',
                'currency': op.currency if op else 'USD',
                'owned_product_id': op.id if op else None,
                'updated_at': item.updated_at,
                'marketplaces': {},
            }
        # Track latest updated_at
        if item.updated_at and item.updated_at > grouped[login]['updated_at']:
            grouped[login]['updated_at'] = item.updated_at

        grouped[login]['marketplaces'][store_key] = {
            'item_id': item.id,
            'status': item.status,
            'error': item.error_message,
            'store_name': item.store.name,
            'store_slug': item.store.slug,
            'marketplace': item.marketplace,
            'sale_price': str(item.listing.price) if item.listing else '',
            'sale_currency': item.listing.currency if item.listing else '',
            'offer_id': item.listing.store_listing_id if item.listing else '',
            'offer_title': item.listing.title if item.listing else '',
        }

    # All system stores for "show all" mode — all active sell/both accounts
    all_system_stores = OrderedDict()
    for acct in IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).order_by('provider', 'name'):
        mp_label = MARKETPLACE_DISPLAY.get(acct.provider, acct.provider)
        all_system_stores[str(acct.id)] = f"{mp_label} ({acct.name})"

    # Check if Google Sheets credential is available
    from apps.inventory.services.sheets_export import get_google_sheets_credential
    has_sheets = get_google_sheets_credential() is not None

    return render(request, 'posting/stock_job_detail.html', {
        'job': job,
        'items': items,
        'grouped_data_json': json.dumps(list(grouped.values()), default=str),
        'job_marketplaces_json': json.dumps(dict(job_stores)),
        'all_marketplaces_json': json.dumps(dict(all_system_stores)),
        'has_sheets_credential': has_sheets,
    })


@ensure_csrf_cookie
@role_required('admin', 'user')
def content_templates_page(request):
    """Manage content templates with {field_name} placeholders."""
    games = Game.objects.filter(is_active=True, slug__in=SUPPORTED_GAME_SLUGS).order_by('name')
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


@ensure_csrf_cookie
@role_required('admin', 'user')
def content_template_editor_page(request, template_id=None):
    """Dedicated full-page template editor with live preview."""
    games = Game.objects.filter(is_active=True, slug__in=SUPPORTED_GAME_SLUGS).order_by('name')
    game_options = [
        {'id': game.id, 'name': game.name, 'slug': game.slug}
        for game in games
    ]

    template_data = 'null'
    if template_id:
        tpl = get_object_or_404(ContentTemplate, id=template_id)
        template_data = json.dumps({
            'id': tpl.id,
            'game_id': tpl.game_id,
            'marketplace': tpl.marketplace,
            'template_type': tpl.template_type,
            'name': tpl.name,
            'body': tpl.body,
        })

    return render(request, 'posting/content_template_editor.html', {
        'games': games,
        'game_options_json': json.dumps(game_options),
        'marketplace_options_json': json.dumps(ContentTemplate.MARKETPLACE_CHOICES),
        'template_type_options_json': json.dumps(ContentTemplate.TEMPLATE_TYPE_CHOICES),
        'template_data_json': template_data,
    })


@ensure_csrf_cookie
@role_required('admin', 'user')
def cosmetic_lists_page(request):
    """Cosmetic list management page."""
    games = Game.objects.filter(is_active=True, slug__in=SUPPORTED_GAME_SLUGS).order_by('name')
    game_options = [
        {'id': game.id, 'name': game.name, 'slug': game.slug}
        for game in games
    ]
    return render(request, 'posting/cosmetic_lists.html', {
        'game_options_json': json.dumps(game_options),
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
        .select_related('game', 'variant')
        .prefetch_related('pool_offers__listing__integration_account')
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
        OfferPool.objects.select_related('game', 'variant', 'credential_spec'),
        id=pool_id,
    )
    pool_offers = list(
        pool.pool_offers.select_related('listing', 'listing__integration_account')
        .order_by('created_at')
    )
    active_pool_offers = [
        offer for offer in pool_offers if offer.status != 'detached'
    ]
    items = pool.items.select_related(
        'owned_product', 'pool_offer',
    ).order_by('order', 'created_at')
    active_offers = (
        OfferPoolActiveOffer.objects.filter(pool_offer__pool=pool)
        .select_related('listing', 'pool_item', 'pool_offer')
        .order_by('-created_at')
    )

    # Linked OwnedProducts via ListingOwnedProduct M2M
    from apps.listings.models import ListingOwnedProduct
    linked_accounts = (
        ListingOwnedProduct.objects
        .filter(listing__pool_offer__pool=pool)
        .select_related('owned_product')
        .distinct()
        .order_by('created_at')
    )

    logs = PostingLog.objects.filter(
        task_name__in=['pool_replenish', 'pool_checker'],
        detail__pool_id=pool.pk,
    ).order_by('-created_at')[:50]

    from apps.posting.models import OfferPoolItemStatus
    consumed_count = pool.items.filter(status=OfferPoolItemStatus.CONSUMED).count()

    return render(request, 'posting/restock_pool_detail.html', {
        'pool': pool,
        'pool_offers': pool_offers,
        'active_pool_offers': active_pool_offers,
        'primary_offer': active_pool_offers[0] if active_pool_offers else None,
        'items': items,
        'active_offers': active_offers,
        'linked_accounts': linked_accounts,
        'logs': logs,
        'consumed_count': consumed_count,
    })
