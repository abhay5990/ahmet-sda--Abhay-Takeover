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
    OfferPoolActiveOffer, OfferPoolActiveOfferStatus, OfferPoolItemStatus,
    PoolOffer, PoolOfferStatus, PoolSaleEvent, PostingJob, PostingLog,
)
from apps.posting.models import GameVariant
from payload_pipeline.core.enums import GameSlug

SUPPORTED_GAME_SLUGS = {gs.value for gs in GameSlug}


# Canonical marketplace/store destinations for every shared stock pool.  Store
# aliases preserve the business-facing labels even where an integration account
# uses its legacy storefront name.
_POOL_MARKETPLACE_SLOTS = (
    {
        'key': 'eldorado_mart',
        'title': 'Eldorado Mart',
        'provider': 'eldorado',
        'store_aliases': ('ezsmurfmart', 'ezmurfmart'),
    },
    {
        'key': 'eldorado_shop',
        'title': 'Eldorado Shop',
        'provider': 'eldorado',
        'store_aliases': ('ezsmurfshop',),
    },
    {
        'key': 'gameboost_csgosmurfkings',
        'title': 'CsgoSmurfkings GameBoost',
        'provider': 'gameboost',
        'store_aliases': ('csgosmurfkings', 'ezsmurfmart', 'ezmurfmart'),
    },
    {
        'key': 'gameboost_gamerinstanty',
        'title': 'GamerInstanty GameBoost',
        'provider': 'gameboost',
        'store_aliases': ('gamerinstanty',),
    },
    {
        'key': 'playerauctions_csgosmurfkings',
        'title': 'CsgoSmurfkings PlayerAuctions',
        'provider': 'playerauctions',
        'store_aliases': ('csgosmurfkings', 'ezsmurfmart', 'ezmurfmart'),
    },
    {
        'key': 'playerauctions_vapenation',
        'title': 'Vapenation PlayerAuctions',
        'provider': 'playerauctions',
        'store_aliases': ('vapenation', 'vapenation234', 'ezsmurfshop'),
    },
)


def _normalize_pool_store_name(name):
    """Return a stable identifier used to match legacy integration names."""
    return ''.join(character for character in (name or '').lower() if character.isalnum())


def _slot_key_for_store(provider, store):
    """Return the canonical slot for a provider/store pair."""
    provider = (provider or '').lower()
    store_key = _normalize_pool_store_name(getattr(store, 'name', ''))
    for slot in _POOL_MARKETPLACE_SLOTS:
        if provider == slot['provider'] and store_key in slot['store_aliases']:
            return slot['key']
    return None


def _slot_key_for_pool_offer(pool_offer):
    """Return the canonical marketplace-slot key for a linked pool offer."""
    return _slot_key_for_store(pool_offer.marketplace, pool_offer.store)


def _pool_offer_priority(pool_offer):
    """Prefer live offers, then the newest configuration for a store slot."""
    status_priority = {
        PoolOfferStatus.ACTIVE: 0,
        PoolOfferStatus.PAUSED: 1,
        PoolOfferStatus.ERROR: 2,
        PoolOfferStatus.DETACHED: 3,
    }
    created_at = pool_offer.created_at
    timestamp = created_at.timestamp() if created_at else 0
    return status_priority.get(pool_offer.status, 4), -timestamp


def _build_pool_marketplace_blocks(pool_offers, items, active_offers, sale_events):
    """Build the six marketplace/store cards shown on a pool detail page.

    An append marketplace can confirm that an item was removed from a remote
    offer, but it does not persist a direct item-to-order relation.  Therefore,
    such consumed items are shown as reconciled while their real order IDs stay
    in the offer-level sale-event history.  PlayerAuctions clone sales retain an
    exact active-offer-to-pool-item relationship and are shown together.
    """
    offers_by_slot = {slot['key']: [] for slot in _POOL_MARKETPLACE_SLOTS}
    unmatched_offers = []
    for pool_offer in pool_offers:
        slot_key = _slot_key_for_pool_offer(pool_offer)
        if slot_key:
            offers_by_slot[slot_key].append(pool_offer)
        else:
            unmatched_offers.append(pool_offer)

    items_by_offer = {}
    unallocated_pending_items = []
    for item in items:
        if (
            item.status == OfferPoolItemStatus.PENDING
            and item.pool_offer_id is None
        ):
            unallocated_pending_items.append(item)
        elif item.pool_offer_id:
            items_by_offer.setdefault(item.pool_offer_id, []).append(item)

    active_by_offer = {}
    sold_active_by_item_id = {}
    for active_offer in active_offers:
        if active_offer.pool_offer_id:
            active_by_offer.setdefault(active_offer.pool_offer_id, []).append(
                active_offer,
            )
        if (
            active_offer.status == OfferPoolActiveOfferStatus.SOLD
            and active_offer.pool_item_id
        ):
            sold_active_by_item_id[active_offer.pool_item_id] = active_offer

    sale_events_by_offer = {}
    sale_event_by_listing = {}
    for sale_event in sale_events:
        if sale_event.pool_offer_id:
            sale_events_by_offer.setdefault(sale_event.pool_offer_id, []).append(
                sale_event,
            )
        # The first event is the newest because the query is ordered by
        # ``-created_at``.  It is the exact order record for a PA cloned offer.
        if sale_event.listing_id and sale_event.listing_id not in sale_event_by_listing:
            sale_event_by_listing[sale_event.listing_id] = sale_event

    def make_block(slot, offers, *, is_additional=False):
        offers = sorted(offers, key=_pool_offer_priority)
        primary_offer = offers[0] if offers else None
        sold_items = []
        sale_history = []
        for offer in offers:
            sale_history.extend(sale_events_by_offer.get(offer.pk, []))
            for item in items_by_offer.get(offer.pk, []):
                sold_active_offer = sold_active_by_item_id.get(item.pk)
                is_sold_clone = bool(sold_active_offer)
                is_consumed = item.status == OfferPoolItemStatus.CONSUMED
                if not (is_sold_clone or is_consumed):
                    continue
                sale_event = (
                    sale_event_by_listing.get(sold_active_offer.listing_id)
                    if sold_active_offer and sold_active_offer.listing_id
                    else None
                )
                sold_items.append({
                    'item': item,
                    'active_offer': sold_active_offer,
                    'order_id': sale_event.order_id if sale_event else None,
                    'sold_at': (
                        sold_active_offer.updated_at
                        if sold_active_offer else item.consumed_at
                    ),
                    'status_label': 'Sold' if is_sold_clone else 'Consumed',
                    'is_exact_order_match': bool(sale_event),
                })

        sold_items.sort(
            key=lambda entry: entry['sold_at'] or entry['item'].updated_at,
            reverse=True,
        )
        sale_history.sort(key=lambda event: event.created_at, reverse=True)
        active_listing_ids = []
        if primary_offer:
            active_listing_ids = [
                active_offer.store_listing_id
                for active_offer in active_by_offer.get(primary_offer.pk, [])
                if active_offer.status == OfferPoolActiveOfferStatus.ACTIVE
            ]

        return {
            'key': slot['key'],
            'title': slot['title'],
            'marketplace': slot['provider'],
            'primary_offer': primary_offer,
            'offer_history_count': len(offers),
            'has_additional_history': len(offers) > 1,
            'active_listing_ids': active_listing_ids,
            'sold_items': sold_items[:6],
            'sold_item_count': len(sold_items),
            'sale_history': sale_history[:6],
            'sale_history_count': len(sale_history),
            'unallocated_pending_count': len(unallocated_pending_items),
            'is_additional': is_additional,
        }

    marketplace_blocks = [
        make_block(slot, offers_by_slot[slot['key']])
        for slot in _POOL_MARKETPLACE_SLOTS
    ]

    # Do not hide a linked offer if an administrator has configured a store name
    # that is not part of the six canonical destinations.
    additional_blocks = []
    for pool_offer in unmatched_offers:
        store = pool_offer.store
        additional_blocks.append(make_block({
            'key': f'additional_{pool_offer.pk}',
            'title': (
                f'{store.name} {pool_offer.marketplace.title()}'
                if store else f'Additional offer #{pool_offer.pk}'
            ),
            'provider': pool_offer.marketplace or 'other',
        }, [pool_offer], is_additional=True))

    return marketplace_blocks, additional_blocks, unallocated_pending_items


_MARKETPLACE_DISPLAY_NAMES = {
    'eldorado': 'Eldorado',
    'gameboost': 'GameBoost',
    'playerauctions': 'PlayerAuctions',
}


def _build_pool_item_views(pool_offers, items, active_offers, sale_events):
    """Build item-level marketplace assignments and one cross-store sale ledger.

    Pool items are assigned to a specific ``PoolOffer`` once dispatch begins.
    That relationship is the authoritative destination for every account.  A
    PlayerAuctions clone sale has an exact active-offer/item/order association;
    append marketplaces retain the destination but only provide a reconciled
    removal signal, so their order IDs are deliberately not guessed.
    """
    slots_by_key = {slot['key']: slot for slot in _POOL_MARKETPLACE_SLOTS}
    offers_by_id = {offer.pk: offer for offer in pool_offers}
    rows_by_slot = {slot['key']: [] for slot in _POOL_MARKETPLACE_SLOTS}
    unmatched_rows_by_offer = {}
    shared_rows = []
    all_rows = []
    sold_history = []

    sold_active_by_item_id = {}
    for active_offer in active_offers:
        if (
            active_offer.status == OfferPoolActiveOfferStatus.SOLD
            and active_offer.pool_item_id
        ):
            sold_active_by_item_id[active_offer.pool_item_id] = active_offer

    sale_event_by_listing = {}
    for sale_event in sale_events:
        # Queries arrive newest first.  A sale event on a PA cloned listing is
        # the only exact item/order link for the item-level ledger.
        if sale_event.listing_id and sale_event.listing_id not in sale_event_by_listing:
            sale_event_by_listing[sale_event.listing_id] = sale_event

    for item in items:
        pool_offer = getattr(item, 'pool_offer', None) or offers_by_id.get(
            item.pool_offer_id,
        )
        reservation = getattr(item, 'reservation', None)
        reservation_store = getattr(reservation, 'store', None)
        reservation_marketplace = (
            getattr(reservation_store, 'provider', '') if reservation_store else ''
        )
        slot_key = (
            _slot_key_for_pool_offer(pool_offer) if pool_offer
            else _slot_key_for_store(reservation_marketplace, reservation_store)
            if reservation_store else None
        )
        slot = slots_by_key.get(slot_key)
        active_offer = sold_active_by_item_id.get(item.pk)
        sale_event = (
            sale_event_by_listing.get(active_offer.listing_id)
            if active_offer and active_offer.listing_id else None
        )
        is_sold_clone = bool(active_offer)
        is_consumed = item.status == OfferPoolItemStatus.CONSUMED
        is_sale_record = is_sold_clone or is_consumed

        if slot:
            destination_title = slot['title']
            marketplace = slot['provider']
        elif pool_offer:
            store = pool_offer.store
            marketplace = pool_offer.marketplace or ''
            destination_title = (
                f'{store.name} {_MARKETPLACE_DISPLAY_NAMES.get(marketplace, marketplace.title())}'
                if store else f'Additional store {pool_offer.pk}'
            )
        elif reservation_store:
            marketplace = reservation_marketplace
            destination_title = (
                f'{reservation_store.name} '
                f'{_MARKETPLACE_DISPLAY_NAMES.get(marketplace, marketplace.title())}'
            )
        else:
            marketplace = ''
            destination_title = 'Shared pool stock'

        listing = pool_offer.listing if pool_offer else None
        row = {
            'item': item,
            'pool_offer': pool_offer,
            'slot_key': slot_key,
            'destination_title': destination_title,
            'marketplace': marketplace,
            'marketplace_display': _MARKETPLACE_DISPLAY_NAMES.get(
                marketplace, marketplace.title(),
            ) if marketplace else 'Shared',
            'store_name': (
                pool_offer.store.name if pool_offer and pool_offer.store
                else reservation_store.name if reservation_store else '—'
            ),
            'offer_id': (
                item.target_offer_id
                or (listing.store_listing_id if listing else '')
            ),
            'is_shared': pool_offer is None and reservation_store is None,
            'is_sold': is_sale_record,
            'sale_status_label': (
                'Order confirmed' if sale_event else (
                    'Sold clone' if is_sold_clone else (
                        'Remote reconciliation' if is_consumed else ''
                    )
                )
            ),
            'order_id': sale_event.order_id if sale_event else None,
            'sold_at': (
                active_offer.updated_at if active_offer else item.consumed_at
            ) if is_sale_record else None,
            'is_exact_order_match': bool(sale_event),
        }
        all_rows.append(row)
        if is_sale_record:
            sold_history.append(row)

        if slot_key:
            rows_by_slot[slot_key].append(row)
        elif pool_offer:
            unmatched_rows_by_offer.setdefault(pool_offer.pk, []).append(row)
        elif reservation_store:
            unmatched_rows_by_offer.setdefault(
                f'reservation_{reservation_store.pk}', [],
            ).append(row)
        else:
            shared_rows.append(row)

    def make_item_block(slot, rows, *, primary_offer=None, is_additional=False):
        return {
            'key': slot['key'],
            'title': slot['title'],
            'marketplace': slot['provider'],
            'primary_offer': primary_offer,
            'rows': rows,
            'item_count': len(rows),
            'listed_count': sum(
                1 for row in rows
                if row['item'].status == OfferPoolItemStatus.PUSHED
            ),
            'processing_count': sum(
                1 for row in rows
                if row['item'].status in {
                    OfferPoolItemStatus.RESERVED,
                    OfferPoolItemStatus.QUEUED,
                }
            ),
            'sold_count': sum(1 for row in rows if row['is_sold']),
            'failed_count': sum(
                1 for row in rows
                if row['item'].status == OfferPoolItemStatus.FAILED
            ),
            'is_additional': is_additional,
        }

    offers_by_slot = {slot['key']: [] for slot in _POOL_MARKETPLACE_SLOTS}
    unmatched_offers = []
    for pool_offer in pool_offers:
        slot_key = _slot_key_for_pool_offer(pool_offer)
        if slot_key:
            offers_by_slot[slot_key].append(pool_offer)
        else:
            unmatched_offers.append(pool_offer)

    item_marketplace_blocks = []
    for slot in _POOL_MARKETPLACE_SLOTS:
        offers = sorted(offers_by_slot[slot['key']], key=_pool_offer_priority)
        item_marketplace_blocks.append(make_item_block(
            slot,
            rows_by_slot[slot['key']],
            primary_offer=offers[0] if offers else None,
        ))

    additional_item_blocks = []
    for pool_offer in unmatched_offers:
        store = pool_offer.store
        marketplace = pool_offer.marketplace or 'other'
        title = (
            f'{store.name} {_MARKETPLACE_DISPLAY_NAMES.get(marketplace, marketplace.title())}'
            if store else f'Additional store {pool_offer.pk}'
        )
        additional_item_blocks.append(make_item_block(
            {
                'key': f'additional_{pool_offer.pk}',
                'title': title,
                'provider': marketplace,
            },
            unmatched_rows_by_offer.get(pool_offer.pk, []),
            primary_offer=pool_offer,
            is_additional=True,
        ))

    reservation_blocks = {}
    for item in items:
        reservation = getattr(item, 'reservation', None)
        store = getattr(reservation, 'store', None)
        if not store:
            continue
        slot_key = _slot_key_for_store(store.provider, store)
        if slot_key:
            continue
        key = f'reservation_{store.pk}'
        if key not in unmatched_rows_by_offer:
            continue
        reservation_blocks.setdefault(key, {
            'store': store,
            'marketplace': store.provider,
        })
    for key, details in reservation_blocks.items():
        store = details['store']
        marketplace = details['marketplace']
        additional_item_blocks.append(make_item_block(
            {
                'key': key,
                'title': f'{store.name} {_MARKETPLACE_DISPLAY_NAMES.get(marketplace, marketplace.title())}',
                'provider': marketplace,
            },
            unmatched_rows_by_offer[key],
            is_additional=True,
        ))

    sold_history.sort(
        key=lambda row: row['sold_at'] or row['item'].updated_at,
        reverse=True,
    )
    return (
        item_marketplace_blocks,
        additional_item_blocks,
        shared_rows,
        sold_history,
        all_rows,
    )


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
    items = list(pool.items.select_related(
        'owned_product',
        'pool_offer__listing__integration_account',
        'reservation__store',
    ).order_by('order', 'created_at'))
    active_offers = list(
        OfferPoolActiveOffer.objects.filter(pool_offer__pool=pool)
        .select_related('listing', 'pool_item', 'pool_item__owned_product', 'pool_offer')
        .order_by('-created_at')
    )
    sale_events = list(
        PoolSaleEvent.objects.filter(pool_offer__pool=pool)
        .select_related('listing', 'pool_offer')
        .order_by('-created_at')
    )
    (
        marketplace_blocks,
        additional_marketplace_blocks,
        unallocated_pending_items,
    ) = _build_pool_marketplace_blocks(
        pool_offers,
        items,
        active_offers,
        sale_events,
    )
    (
        item_marketplace_blocks,
        additional_item_marketplace_blocks,
        shared_item_rows,
        sold_item_history,
        pool_item_rows,
    ) = _build_pool_item_views(
        pool_offers,
        items,
        active_offers,
        sale_events,
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

    consumed_count = sum(
        1 for item in items if item.status == OfferPoolItemStatus.CONSUMED
    )

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
        'marketplace_blocks': marketplace_blocks,
        'additional_marketplace_blocks': additional_marketplace_blocks,
        'unallocated_pending_items': unallocated_pending_items,
        'item_marketplace_blocks': item_marketplace_blocks,
        'additional_item_marketplace_blocks': additional_item_marketplace_blocks,
        'shared_item_rows': shared_item_rows,
        'sold_item_history': sold_item_history,
        'pool_item_rows': pool_item_rows,
    })
