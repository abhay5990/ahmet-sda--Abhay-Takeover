"""Relist service — delete a marketplace listing and re-create it with the same payload.

Gives the listing a fresh expiry timer on the marketplace.  Works for all
three supported providers: Eldorado, PlayerAuctions, Gameboost.

Usage:
    from apps.posting.services.relist import relist_listing
    result = relist_listing(listing)
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from django.db import transaction
from django.utils import timezone

from apps.integrations.providers import registry
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.models import OfferPool, PoolOffer, PoolOfferStatus
from core.marketplace.normalizers import normalize_offer_response
from core.marketplace.payload_extractor import extract_create_payload

logger = logging.getLogger(__name__)


class RelistResult(NamedTuple):
    ok: bool
    new_listing: Listing | None = None
    error: str = ''


def relist_listing(
    listing: Listing,
    *,
    augmented_game_override: dict | None = None,
) -> RelistResult:
    """Delete *listing* from its marketplace and re-create it.

    Steps:
        1. Extract a create-ready payload from ``listing.raw_data``.
        2. Delete the old offer via the provider API.
        3. Create a new offer with the same payload.
        4. Atomically update the DB: old listing → DELETED, new listing created,
           OwnedProduct links + OfferPool transferred.

    ``augmented_game_override`` (Eldorado only): when provided, replaces the
    payload's ``augmentedGame`` block before recreating.  Used to push freshly
    rebuilt offer attributes onto a listing while preserving its price, title,
    images and credentials.  Eldorado offers are immutable after creation
    (the update endpoint rejects PUT/PATCH/POST with 405), so attribute changes
    must go through delete + recreate.

    Returns a ``RelistResult`` with the new ``Listing`` on success.
    """
    store = listing.integration_account
    if not store or not store.credential:
        return RelistResult(ok=False, error='No integration account or credential')

    marketplace = store.provider

    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    provider = registry.get_provider(marketplace)
    client = registry.get_or_build_client(
        marketplace,
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    # 1. Build payload --------------------------------------------------------
    payload = _extract_payload(
        listing,
        marketplace,
        client=client,
        proxy_group=proxy_group,
    )
    if payload is None:
        return RelistResult(ok=False, error='Cannot extract payload from raw_data')

    # Override attributes (Eldorado): swap in the freshly rebuilt augmentedGame.
    if augmented_game_override is not None and marketplace == 'eldorado':
        payload['augmentedGame'] = augmented_game_override

    # Eldorado requires credential data — fetch from API if missing in raw_data
    if marketplace == 'eldorado':
        secrets = payload.get('accountSecretDetails')
        has_secrets = bool(secrets) and (
            (isinstance(secrets, list) and len(secrets) > 0)
            or (isinstance(secrets, str) and len(secrets.strip()) > 0)
        )
        if not has_secrets:
            secrets = _fetch_eldorado_credentials(listing, proxy_pool)
            if not secrets:
                return RelistResult(
                    ok=False,
                    error='Listing has no credential data and could not fetch from API.',
                )
            payload['accountSecretDetails'] = secrets
            payload['details']['pricing']['quantity'] = len(secrets)

    # 2. Delete old offer (skip if already deleted) ----------------------------
    if listing.status != ListingStatus.DELETED:
        delete_ok = _delete_offer(listing, marketplace, proxy_pool)
        if not delete_ok:
            return RelistResult(ok=False, error='Failed to delete old marketplace offer')

    # 3. Create new offer -----------------------------------------------------
    try:
        product_data = {'payload': payload}
        if proxy_group:
            product_data['proxy_group'] = proxy_group
        api_result = provider.create_listing(client, product_data)
    except Exception as e:
        logger.error('Relist create failed for listing #%s: %s', listing.id, e)
        # Old offer already deleted — mark listing DELETED so state is consistent.
        _mark_deleted(listing)
        return RelistResult(ok=False, error=f'Create failed (old offer deleted): {e}')

    # Check API-level failure first
    if hasattr(api_result, 'ok') and not api_result.ok:
        error_msg = getattr(api_result, 'error', None) or str(api_result)
        logger.error(
            'Relist create API error for listing #%s: %s', listing.id, error_msg,
        )
        _mark_deleted(listing)
        return RelistResult(ok=False, error=f'Create API failed (old offer deleted): {error_msg}')

    new_offer_id = _extract_offer_id(api_result, marketplace)
    if not new_offer_id:
        logger.error(
            'Relist: could not extract offer ID for listing #%s. '
            'api_result type=%s, data=%s',
            listing.id, type(api_result).__name__,
            getattr(api_result, 'data', api_result),
        )
        _mark_deleted(listing)
        return RelistResult(
            ok=False,
            error='Create succeeded but could not extract new offer ID',
        )

    # 4. Update DB atomically -------------------------------------------------
    response_data = api_result.data if hasattr(api_result, 'data') else api_result
    new_listing = _replace_in_db(
        listing,
        new_offer_id,
        response_data,
        payload,
        client=client,
        proxy_group=proxy_group,
    )

    logger.info(
        'Relisted listing #%s → #%s (offer_id=%s, provider=%s)',
        listing.id, new_listing.id, new_offer_id, marketplace,
    )

    return RelistResult(ok=True, new_listing=new_listing)


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------

def _extract_payload(
    listing: Listing,
    marketplace: str,
    *,
    client=None,
    proxy_group=None,
) -> dict | None:
    """Extract a create-ready payload from listing.raw_data.

    Handles legacy envelopes and sync-style flat marketplace payloads.
    """
    raw = listing.raw_data or {}
    payload = extract_create_payload(
        raw,
        marketplace,
        client=client,
        proxy_group=proxy_group,
    )
    if payload is not None:
        return payload

    logger.warning(
        'Cannot extract relist payload for listing #%s (provider=%s, '
        'raw_data keys=%s).',
        listing.id, marketplace, list(raw.keys())[:10],
    )
    return None


# ---------------------------------------------------------------------------
# Credential fetching
# ---------------------------------------------------------------------------

def _fetch_eldorado_credentials(
    listing: Listing, proxy_pool: Any,
) -> list[str]:
    """Fetch credential secrets from Eldorado API for a listing.

    Returns a list of secretDetails strings, or empty list on failure.
    """
    store = listing.integration_account
    try:
        provider = registry.get_provider('eldorado')
        client = registry.get_or_build_client(
            'eldorado', store.credential, proxy_pool=proxy_pool,
        )
        result = provider.fetch_offer_account_details(client, listing.store_listing_id)
        if not result or (hasattr(result, 'ok') and not result.ok):
            logger.warning(
                'Credential fetch failed for listing #%s: API returned error',
                listing.id,
            )
            return []

        data = result.data if hasattr(result, 'data') else result
        if not data:
            return []

        secrets: list[str] = []
        # Try accountsDetails first, then secretDetails
        for attr in ('accountsDetails', 'secretDetails'):
            source = getattr(data, attr, None)
            if source:
                for entry in source:
                    sd = entry.secretDetails if hasattr(entry, 'secretDetails') else (
                        entry.get('secretDetails', '') if isinstance(entry, dict) else ''
                    )
                    if sd:
                        secrets.append(sd)
                break

        logger.info(
            'Fetched %d credentials from API for listing #%s',
            len(secrets), listing.id,
        )
        return secrets
    except Exception as e:
        logger.warning(
            'Credential fetch exception for listing #%s: %s', listing.id, e,
        )
        return []


# ---------------------------------------------------------------------------
# Marketplace operations
# ---------------------------------------------------------------------------

def _delete_offer(listing: Listing, marketplace: str, proxy_pool: Any) -> bool:
    """Delete the offer from the marketplace. Returns True on success."""
    store = listing.integration_account
    try:
        provider = registry.get_provider(marketplace)
        client = registry.get_or_build_client(
            marketplace, store.credential, proxy_pool=proxy_pool,
        )
        provider.delete_listing(client, listing.store_listing_id)
        return True
    except Exception as e:
        logger.error(
            'Relist delete failed for listing #%s (%s): %s',
            listing.id, listing.store_listing_id, e,
        )
        return False


def _extract_offer_id(api_result: Any, marketplace: str) -> str | None:
    """Extract the new offer ID from the create_offer API response."""
    if api_result is None:
        return None

    # SDK ApiResult wrapper
    if hasattr(api_result, 'data') and api_result.data is not None:
        data = api_result.data
        # PlayerAuctions: response object with .offer_id
        if hasattr(data, 'offer_id') and data.offer_id is not None:
            return str(data.offer_id)
        # Eldorado / Gameboost: response object with .id
        if hasattr(data, 'id') and data.id is not None:
            return str(data.id)
        # Dict response
        if isinstance(data, dict):
            return str(data.get('id') or data.get('offerId') or data.get('offer_id') or '')
        return str(data) if data else None

    # Direct dict response (PA)
    if isinstance(api_result, dict):
        return str(api_result.get('id') or api_result.get('offerId') or api_result.get('offer_id') or '')

    # Object with .id
    if hasattr(api_result, 'id'):
        return str(api_result.id)

    return None


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def _mark_deleted(listing: Listing) -> None:
    """Mark a listing as DELETED (fallback when create fails after delete)."""
    listing.status = ListingStatus.DELETED
    listing.removed_at = timezone.now()
    listing.save(update_fields=['status', 'removed_at', 'updated_at'])


def _replace_in_db(
    old_listing: Listing,
    new_offer_id: str,
    response_data: Any,
    payload: dict,
    *,
    client=None,
    proxy_group=None,
) -> Listing:
    """Atomically replace old listing with a new one, transfer links and pools."""
    with transaction.atomic():
        # Capture links before modifying old listing
        owned_products = list(
            ListingOwnedProduct.objects
            .filter(listing=old_listing)
            .values_list('owned_product_id', flat=True)
        )
        legacy_pools = list(OfferPool.objects.filter(listing=old_listing))
        pool_offers = list(
            PoolOffer.objects.select_for_update().filter(listing=old_listing)
        )

        # Mark old listing DELETED
        old_listing.status = ListingStatus.DELETED
        old_listing.removed_at = timezone.now()
        old_listing.save(update_fields=['status', 'removed_at', 'updated_at'])

        marketplace = old_listing.integration_account.provider
        new_raw_data = normalize_offer_response(
            marketplace,
            response_data,
            payload=payload,
            client=client,
            proxy_group=proxy_group,
        )

        # Create new listing
        new_listing = Listing.objects.create(
            integration_account=old_listing.integration_account,
            game=old_listing.game,
            store_listing_id=new_offer_id,
            product_category=old_listing.product_category,
            variant=old_listing.variant,
            status=ListingStatus.LISTED,
            title=old_listing.title,
            price=old_listing.price,
            currency=old_listing.currency,
            listed_at=timezone.now(),
            is_instant=old_listing.is_instant,
            dropship_product=old_listing.dropship_product,
            raw_data=new_raw_data,
        )

        # Transfer OwnedProduct links
        if owned_products:
            ListingOwnedProduct.objects.bulk_create([
                ListingOwnedProduct(listing=new_listing, owned_product_id=op_id)
                for op_id in owned_products
            ])

        # Transitional dual-write for the legacy relation.
        for pool in legacy_pools:
            pool.listing = new_listing
            pool.save(update_fields=['listing', 'updated_at'])

        # Move the operational link and clear the temporary signal error.
        for pool_offer in pool_offers:
            pool_offer.listing = new_listing
            pool_offer.status = PoolOfferStatus.ACTIVE
            pool_offer.last_error = ''
            pool_offer.save(update_fields=[
                'listing', 'status', 'last_error', 'updated_at',
            ])

    return new_listing
