"""Listing creation helper — shared between stock + PA batch paths (and dropship).

Centralises the Listing + ListingOwnedProduct creation that was previously
duplicated across ``_process_item`` (non-PA) and ``_flush_pa_batch`` (PA).
"""

from __future__ import annotations

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


def persist_success(
    *,
    item: PostingJobItem,
    job: PostingJob,
    owned_product,
    store_listing_id: str,
    sub_platform: str,
    final_price: Decimal,
    payload: dict | None = None,
    response_data: Any = None,
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
        sub_platform: Resolved sub-platform (may be empty).
        final_price: Final USD price to store on the Listing.
        payload: The marketplace payload that was POSTed (for title/currency/audit).
        response_data: The raw API response (Pydantic model, dict, or None).

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

    # raw_data: store both sent payload and API response for audit
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
        sub_platform=sub_platform,
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
    return listing
