"""Listing creation helper — shared between stock + PA batch paths (and dropship).

Centralises the Listing + ListingOwnedProduct creation that was previously
duplicated across ``_process_item`` (non-PA) and ``_flush_pa_batch`` (PA).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.models import PostingJob, PostingJobItem, PostingJobItemStatus
from apps.posting.services.shared.utils import (
    extract_currency_from_payload,
    extract_price_from_response,
    extract_title_from_payload,
    extract_title_from_response,
    serialize_response,
)

logger = logging.getLogger(__name__)


def persist_success(
    *,
    item: PostingJobItem,
    job: PostingJob,
    owned_product,
    store_listing_id: str,
    variant_slug: str,
    final_price: Decimal,
    payload: dict | None = None,
    response_data: Any = None,
    raw_data_override: dict | None = None,
) -> Listing:
    """Create Listing + ListingOwnedProduct and mark ``item`` as SUCCESS.

    The caller is responsible for ``item.save()`` because update_fields
    differs between the non-PA path (``_process_item``) and the PA batch
    path (``_flush_pa_batch``).

    Args:
        item: PostingJobItem being processed. ``item.listing`` and
            ``item.status`` are mutated in-memory but not saved.
        job: Parent PostingJob (provides the game for the Listing title).
        owned_product: OwnedProduct instance linked to the new Listing.
        store_listing_id: Marketplace-side offer/listing identifier.
        variant_slug: Resolved variant slug (may be empty).
        final_price: Final USD price to store on the Listing.
        payload: The marketplace payload that was POSTed (for title/currency/audit).
        response_data: The raw API response (Pydantic model, dict, or None).
        raw_data_override: Normalized raw_data to persist instead of the
            legacy ``{"payload": ..., "response": ...}`` envelope.

    Returns:
        The newly-created Listing instance.
    """
    marketplace = item.marketplace

    # Title: response > payload > generic fallback
    title = extract_title_from_response(response_data, marketplace)
    if not title and payload:
        title = extract_title_from_payload(payload, marketplace)
    if not title:
        title = f"{job.game.name} — {owned_product.login}"

    # Price: prefer confirmed USD price from response, fallback to calculated
    confirmed_price = extract_price_from_response(response_data, marketplace)
    price = confirmed_price if confirmed_price is not None else final_price

    # Currency: from payload when available
    currency = extract_currency_from_payload(payload, marketplace) if payload else 'USD'

    if raw_data_override is not None:
        raw_data = raw_data_override
    else:
        raw_data: dict = {}
        if payload:
            raw_data['payload'] = payload
        if response_data is not None:
            raw_data['response'] = serialize_response(response_data)

    listing = Listing.objects.create(
        is_instant=True,
        integration_account=item.store,
        game=job.game,
        store_listing_id=store_listing_id,
        variant=variant_slug,
        status=ListingStatus.LISTED,
        title=title,
        price=price,
        currency=currency,
        listed_at=timezone.now(),
        raw_data=raw_data,
    )
    ListingOwnedProduct.objects.create(
        listing=listing,
        owned_product=owned_product,
    )
    item.listing = listing
    item.status = PostingJobItemStatus.SUCCESS

    # Dispatch hook: pool_dispatch job → finalize reservation
    _dispatch_cfg = (job.settings or {}).get('_pool_dispatch')
    if _dispatch_cfg and isinstance(_dispatch_cfg, dict) and _dispatch_cfg.get('pool_id'):
        try:
            _finalize_dispatch_success(
                dispatch_cfg=_dispatch_cfg,
                listing=listing,
                owned_products=[owned_product],
                marketplace=marketplace,
            )
        except Exception:
            logger.exception(
                'listing_writer: failed to finalize dispatch listing %d (pool %d)',
                listing.id, _dispatch_cfg['pool_id'],
            )
    # Stock-start auto-link hook: only for non-dispatch pool jobs
    elif (job.settings or {}).get('_pool'):
        _pool_cfg = job.settings['_pool']
        if isinstance(_pool_cfg, dict) and _pool_cfg.get('pool_id'):
            try:
                _auto_link_listing_to_pool(
                    pool_id=_pool_cfg['pool_id'],
                    listing=listing,
                    owned_products=[owned_product],
                    target_count=_pool_cfg.get('target_count', 5),
                    threshold=_pool_cfg.get('threshold', 2),
                    marketplace=marketplace,
                )
            except Exception:
                logger.exception(
                    'listing_writer: failed to auto-link listing %d to pool %d',
                    listing.id, _pool_cfg['pool_id'],
                )

    return listing


def persist_multi_cred_success(
    *,
    items: list[PostingJobItem],
    job: PostingJob,
    owned_products: list,
    store_listing_id: str,
    variant_slug: str,
    final_price: Decimal,
    payload: dict | None = None,
    response_data: Any = None,
    raw_data_override: dict | None = None,
) -> Listing:
    """Create ONE Listing and link ALL owned_products for a multi-cred offer.

    Similar to ``persist_success`` but creates a single listing for
    multiple credentials (accounts) that were posted as one marketplace
    offer.  Each item is marked SUCCESS and points to the same listing.

    Args:
        items: All PostingJobItems in the multi-cred batch.
        job: Parent PostingJob.
        owned_products: OwnedProduct instances, one per item (same order).
        store_listing_id: Marketplace-side offer identifier.
        variant_slug: Resolved variant slug.
        final_price: Final USD price.
        payload: The merged marketplace payload.
        response_data: Raw API response.
        raw_data_override: Normalized raw_data.

    Returns:
        The newly-created Listing instance.
    """
    first_item = items[0]
    marketplace = first_item.marketplace

    title = extract_title_from_response(response_data, marketplace)
    if not title and payload:
        title = extract_title_from_payload(payload, marketplace)
    if not title:
        title = f"{job.game.name} — {len(items)} accounts"

    confirmed_price = extract_price_from_response(response_data, marketplace)
    price = confirmed_price if confirmed_price is not None else final_price

    currency = extract_currency_from_payload(payload, marketplace) if payload else 'USD'

    if raw_data_override is not None:
        raw_data = raw_data_override
    else:
        raw_data: dict = {}
        if payload:
            raw_data['payload'] = payload
        if response_data is not None:
            raw_data['response'] = serialize_response(response_data)

    listing = Listing.objects.create(
        is_instant=True,
        integration_account=first_item.store,
        game=job.game,
        store_listing_id=store_listing_id,
        variant=variant_slug,
        status=ListingStatus.LISTED,
        title=title,
        price=price,
        currency=currency,
        listed_at=timezone.now(),
        raw_data=raw_data,
    )

    for item, owned_product in zip(items, owned_products):
        ListingOwnedProduct.objects.create(
            listing=listing,
            owned_product=owned_product,
        )
        item.listing = listing
        item.status = PostingJobItemStatus.SUCCESS
        item.save(update_fields=['status', 'listing', 'error_message', 'updated_at'])

    # Dispatch hook: pool_dispatch job → finalize reservation
    _dispatch_cfg = (job.settings or {}).get('_pool_dispatch')
    if _dispatch_cfg and isinstance(_dispatch_cfg, dict) and _dispatch_cfg.get('pool_id'):
        try:
            _finalize_dispatch_success(
                dispatch_cfg=_dispatch_cfg,
                listing=listing,
                owned_products=list(owned_products),
                marketplace=first_item.marketplace,
            )
        except Exception:
            logger.exception(
                'listing_writer: failed to finalize dispatch listing %d (multi-cred, pool %d)',
                listing.id, _dispatch_cfg['pool_id'],
            )
    # Stock-start auto-link hook: only for non-dispatch pool jobs
    elif (job.settings or {}).get('_pool'):
        _pool_cfg = job.settings['_pool']
        if isinstance(_pool_cfg, dict) and _pool_cfg.get('pool_id'):
            try:
                _auto_link_listing_to_pool(
                    pool_id=_pool_cfg['pool_id'],
                    listing=listing,
                    owned_products=list(owned_products),
                    target_count=_pool_cfg.get('target_count', 5),
                    threshold=_pool_cfg.get('threshold', 2),
                    marketplace=first_item.marketplace,
                )
            except Exception:
                logger.exception(
                    'listing_writer: failed to auto-link listing %d to pool %d (multi-cred)',
                    listing.id, _pool_cfg['pool_id'],
                )

    return listing


def _auto_link_listing_to_pool(
    *,
    pool_id: int,
    listing: Listing,
    owned_products: list,
    target_count: int,
    threshold: int,
    marketplace: str,
) -> None:
    """Create PoolOffer + OfferPoolItems for a newly posted listing.

    Called from persist_success() and persist_multi_cred_success() when the
    job was created with pool_config. Supports single and multi-credential offers.
    Non-fatal: any exception is caught and logged by the caller.
    """
    from django.db import transaction

    from apps.posting.models import (
        OfferPool,
        OfferPoolActiveOffer,
        OfferPoolItem,
        OfferPoolItemStatus,
        PoolOffer,
        PoolOfferStatus,
        PoolOfferStrategy,
    )

    strategy = (
        PoolOfferStrategy.CLONE
        if marketplace == 'playerauctions'
        else PoolOfferStrategy.APPEND
    )
    max_concurrent = 10 if strategy == PoolOfferStrategy.CLONE else None
    cred_count = len(owned_products)

    pool = OfferPool.objects.get(pk=pool_id)

    with transaction.atomic():
        pool_offer = PoolOffer.objects.create(
            pool=pool,
            listing=listing,
            strategy=strategy,
            target_count=target_count,
            threshold=threshold,
            max_concurrent=max_concurrent,
            current_remote_count=cred_count,
            status=PoolOfferStatus.ACTIVE,
        )

        now = timezone.now()
        base_order = pool.items.count()
        first_item = None
        for i, owned_product in enumerate(owned_products):
            pool_item = OfferPoolItem.objects.create(
                pool=pool,
                owned_product=owned_product,
                pool_offer=pool_offer,
                status=OfferPoolItemStatus.PUSHED,
                target_offer_id=listing.store_listing_id,
                remote_state='present',
                pushed_at=now,
                order=base_order + i,
            )
            if first_item is None:
                first_item = pool_item

        if strategy == PoolOfferStrategy.CLONE and first_item is not None:
            OfferPoolActiveOffer.objects.create(
                pool=pool,
                pool_offer=pool_offer,
                listing=listing,
                pool_item=first_item,
                store_listing_id=listing.store_listing_id,
            )


def _finalize_dispatch_success(
    *,
    dispatch_cfg: dict,
    listing,
    owned_products: list,
    marketplace: str,
) -> None:
    """Create PoolOffer + mark reserved items PUSHED for a pool dispatch job.

    Called from persist_success() / persist_multi_cred_success() when the job
    was created via dispatch_offer_from_pool() (settings['_pool_dispatch']).

    Idempotent: if a PoolOffer already exists for this listing it is reused.
    """
    from django.db import transaction

    from apps.posting.models import (
        OfferPool,
        OfferPoolActiveOffer,
        PoolDispatchReservation,
        PoolDispatchReservationStatus,
        PoolOffer,
        PoolOfferStatus,
        PoolOfferStrategy,
    )
    from apps.posting.services.pool.dispatcher import finalize_reserved_items_for_new_offer

    pool_id = dispatch_cfg.get('pool_id')
    reservation_id = dispatch_cfg.get('reservation_id')
    target_count = dispatch_cfg.get('target_count', 5)
    threshold = dispatch_cfg.get('threshold', 2)
    max_concurrent = dispatch_cfg.get('max_concurrent')
    strategy = dispatch_cfg.get('strategy') or PoolOfferStrategy.strategy_for_provider(marketplace)

    pool = OfferPool.objects.get(pk=pool_id)

    with transaction.atomic():
        # Idempotency: reuse existing PoolOffer for this listing
        pool_offer, created = PoolOffer.objects.get_or_create(
            listing=listing,
            defaults={
                'pool': pool,
                'strategy': strategy,
                'target_count': target_count,
                'threshold': threshold,
                'max_concurrent': max_concurrent,
                'current_remote_count': len(owned_products),
                'status': PoolOfferStatus.ACTIVE,
            },
        )

        if strategy == PoolOfferStrategy.CLONE and created:
            # PA clone: create OfferPoolActiveOffer for this listing
            # (items will be linked below)
            pass

        if reservation_id:
            try:
                reservation = PoolDispatchReservation.objects.get(pk=reservation_id)
                finalize_reserved_items_for_new_offer(
                    reservation,
                    pool_offer,
                    listing=listing,
                    owned_products=owned_products,
                )
            except PoolDispatchReservation.DoesNotExist:
                logger.warning(
                    'listing_writer: reservation #%s not found for dispatch finalize',
                    reservation_id,
                )

        # PA clone: create OfferPoolActiveOffer entries for each success item
        if strategy == PoolOfferStrategy.CLONE:
            from apps.posting.models import OfferPoolItem
            for owned_product in owned_products:
                pool_item = (
                    OfferPoolItem.objects.filter(
                        pool=pool,
                        owned_product=owned_product,
                        pool_offer=pool_offer,
                    ).first()
                )
                if pool_item:
                    OfferPoolActiveOffer.objects.get_or_create(
                        pool_offer=pool_offer,
                        store_listing_id=listing.store_listing_id,
                        defaults={
                            'pool': pool,
                            'listing': listing,
                            'pool_item': pool_item,
                        },
                    )


def add_failed_owned_products_to_pool(job: PostingJob, owned_products: list) -> None:
    """Add failed owned products to pool as PENDING items.

    Called when posting fails and the job was created with pool_config.
    Keeps credentials in pool inventory so they can be replenished to a
    future linked offer. Non-fatal: any exception is logged and swallowed.
    """
    _pool_cfg = (job.settings or {}).get('_pool')
    if not (_pool_cfg and isinstance(_pool_cfg, dict) and _pool_cfg.get('pool_id')):
        return
    pool_id = _pool_cfg['pool_id']

    from apps.posting.models import OfferPool, OfferPoolItem, OfferPoolItemStatus

    try:
        pool = OfferPool.objects.get(pk=pool_id)
        base_order = pool.items.count()
        for i, owned_product in enumerate(owned_products):
            if owned_product is None:
                continue
            OfferPoolItem.objects.get_or_create(
                pool=pool,
                owned_product=owned_product,
                defaults={
                    'status': OfferPoolItemStatus.PENDING,
                    'order': base_order + i,
                },
            )
    except Exception:
        logger.exception(
            'listing_writer: failed to add owned products to pool %d after posting failure',
            pool_id,
        )
