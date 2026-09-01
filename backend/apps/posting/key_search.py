"""Authenticated, exact-match key search for safe SDA record location lookup."""
from urllib.parse import urlencode

from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse

from apps.accounts.decorators import role_required
from apps.inventory.models import DropshipProduct, OwnedProduct
from apps.listings.models import Listing
from apps.posting.models import OfferPoolItem, PostingJobItem


_RESULT_LIMIT = 100


def _key_candidates(query: str) -> tuple[str, ...]:
    """Allow an optional leading # while retaining exact matching semantics."""
    normalized = query.strip()
    bare = normalized[1:] if normalized.startswith('#') else normalized
    return tuple(dict.fromkeys(value for value in (normalized, bare, f'#{bare}') if value))


def _exact_filter(fields: tuple[str, ...], values: tuple[str, ...]) -> Q:
    condition = Q()
    for field in fields:
        for value in values:
            condition |= Q(**{f'{field}__iexact': value})
    return condition


def _location_result(*, kind, key, state, game, location, detail, url):
    return {
        'kind': kind,
        'key': key,
        'state': state,
        'game': game or '—',
        'location': location,
        'detail': detail or '',
        'url': url,
    }


@role_required('admin', 'user')
def key_search_page(request):
    """Render safe, exact locations for a reference key, source ID, or offer ID."""
    query = request.GET.get('q', '').strip()[:128]
    candidates = _key_candidates(query) if query else ()
    results = []

    if candidates:
        owned_filter = _exact_filter(('ref_key', 'source_product_id', 'login'), candidates)
        for product in (
            OwnedProduct.objects.filter(owned_filter)
            .select_related('game', 'category')
            .order_by('-updated_at')[:_RESULT_LIMIT]
        ):
            results.append(_location_result(
                kind='Owned stock',
                key=product.ref_key or product.source_product_id or query,
                state=product.get_status_display(),
                game=product.game.name if product.game else None,
                location=f'Inventory product #{product.pk}',
                detail=product.category.title,
                url=reverse('inventory:product_detail', args=[product.pk]),
            ))

        listing_filter = _exact_filter((
            'store_listing_id',
            'listing_owned_products__owned_product__ref_key',
            'listing_owned_products__owned_product__source_product_id',
            'listing_owned_products__owned_product__login',
        ), candidates)
        for listing in (
            Listing.objects.filter(listing_filter)
            .select_related('game', 'integration_account')
            .distinct().order_by('-updated_at')[:_RESULT_LIMIT]
        ):
            store = listing.integration_account.name if listing.integration_account else ''
            results.append(_location_result(
                kind='Marketplace listing',
                key=query,
                state=listing.get_status_display(),
                game=listing.game.name if listing.game else None,
                location=f'Listing #{listing.pk}',
                detail=f'{store} · offer {listing.store_listing_id}' if store else f'offer {listing.store_listing_id}',
                url=reverse('listings:detail', args=[listing.pk]),
            ))

        dropship_filter = _exact_filter(('source_product_id',), candidates)
        for product in (
            DropshipProduct.objects.filter(dropship_filter)
            .select_related('game').order_by('-updated_at')[:_RESULT_LIMIT]
        ):
            results.append(_location_result(
                kind='Dropship product',
                key=product.source_product_id,
                state=product.get_status_display(),
                game=product.game.name if product.game else None,
                location=f'Dropship product #{product.pk}',
                detail=product.product_title,
                url=f"{reverse('posting:dropship_items')}?{urlencode({'q': product.source_product_id})}",
            ))

        pool_filter = _exact_filter((
            'owned_product__ref_key', 'owned_product__source_product_id', 'owned_product__login',
        ), candidates)
        for item in (
            OfferPoolItem.objects.filter(pool_filter)
            .select_related('pool', 'pool__game', 'owned_product__game', 'pool_offer__listing__integration_account')
            .order_by('-updated_at')[:_RESULT_LIMIT]
        ):
            store = ''
            if item.pool_offer and item.pool_offer.listing and item.pool_offer.listing.integration_account:
                store = item.pool_offer.listing.integration_account.name
            game = item.owned_product.game or item.pool.game
            results.append(_location_result(
                kind='Auto Restock pool',
                key=item.owned_product.ref_key or item.owned_product.source_product_id or query,
                state=item.get_status_display(),
                game=game.name if game else None,
                location=f'Pool #{item.pool_id} · item #{item.pk}',
                detail=store or item.pool.name,
                url=reverse('posting:restock_pool_detail', args=[item.pool_id]),
            ))

        posting_filter = _exact_filter((
            'owned_product__ref_key', 'owned_product__source_product_id', 'owned_product__login',
        ), candidates)
        for item in (
            PostingJobItem.objects.filter(posting_filter)
            .select_related('job', 'job__game', 'store')
            .order_by('-updated_at')[:_RESULT_LIMIT]
        ):
            results.append(_location_result(
                kind='Posting job',
                key=query,
                state=item.get_status_display(),
                game=item.job.game.name if item.job.game else None,
                location=f'Job #{item.job_id} · item #{item.pk}',
                detail=item.store.name,
                url=reverse('posting:stock_job_detail', args=[item.job_id]),
            ))

    return render(request, 'posting/key_search.html', {
        'q': query,
        'results': results,
        'searched': bool(query),
    })
