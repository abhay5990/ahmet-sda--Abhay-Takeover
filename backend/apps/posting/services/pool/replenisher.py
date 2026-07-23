"""Offer pool replenisher — pushes credentials to marketplace offers.

Handles three strategies:
- Eldorado: fetch current creds, append new, update_offer (recreate on rate limit)
- Gameboost: add_offer_credentials endpoint
- PlayerAuctions: clone offers with new credentials
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.models import (
    GameVariant,
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PoolOffer,
    PostingLog,
    PostingLogLevel,
)

from apps.posting.pipeline import adapter
from apps.posting.services.shared.pricing import STOCK_PRICING_BASELINE
from apps.posting.services.shared.utils import extract_listing_id
from apps.posting.services.variant_context import build_variant_context
from apps.posting.services.variant_routing import VariantRouter
from payload_pipeline.core.contracts import ListingKind
from apps.posting.services.stock.pa_relay_poster import (
    PARelayPoster,
    fetch_relay_token,
    pa_encrypt,
    pa_fake_owner_info,
    pa_sanitize,
)
from apps.posting.services.stock.pa_tracking import (
    append_tracking_code_for_code,
    pool_clone_tracking_code,
)
from core.marketplace.normalizers import normalize_offer_response
from core.marketplace.payload_extractor import extract_create_payload

from .formatter import (
    build_credential_bundle,
    build_credential_render_context,
    format_credential_by_spec,
    format_credential_for_marketplace,
    render_template,
)
from .allocation import (
    claim_pending_items,
    mark_item_failed,
    mark_items_pushed as finalize_items_pushed,
    release_claims_as_pending,
)

logger = logging.getLogger(__name__)

TASK_NAME = 'pool_replenish'

_PA_SOURCE_REBUILD_DESCRIPTION = (
    'Instant delivery. Account access details are provided automatically '
    'after purchase. Please review the listing title for included features.'
)


def _description_from_listing(listing: Listing | None) -> str:
    """Read a display description from the durable local listing payload."""
    raw = getattr(listing, 'raw_data', None) or {}
    payload = raw.get('payload') if isinstance(raw.get('payload'), dict) else {}
    details = raw.get('details') if isinstance(raw.get('details'), dict) else {}
    for value in (
        raw.get('description'), raw.get('offerDesc'),
        payload.get('offerDesc'), payload.get('description'),
        details.get('offerDesc'), details.get('description'),
    ):
        text = str(value or '').strip()
        if text:
            return text
    return ''


def _canonical_pa_offer_description(pool: OfferPool) -> str:
    """Return the real description from a sibling target of the same pool.

    A PA parent listing created by an older worker may contain only a generic
    placeholder.  Prefer another local marketplace target's authored copy,
    which is the stable and reviewable source for the shared offer content.
    """
    aggregate = getattr(pool, 'aggregate', None) or pool
    current_offer = getattr(pool, 'pool_offer', None)
    current_offer_id = getattr(current_offer, 'pk', None)
    candidates: list[tuple[int, str]] = []
    for sibling in aggregate.pool_offers.select_related('listing__integration_account').order_by('pk'):
        if sibling.pk == current_offer_id:
            continue
        listing = sibling.listing
        provider = str(getattr(getattr(listing, 'integration_account', None), 'provider', '')).lower()
        text = _description_from_listing(listing)
        if not text or text == _PA_SOURCE_REBUILD_DESCRIPTION:
            continue
        priority = 0 if provider == 'gameboost' else 1 if provider == 'eldorado' else 2
        candidates.append((priority, text))
    if not candidates:
        return ''
    candidates.sort(key=lambda candidate: candidate[0])
    return candidates[0][1]


def _ensure_pa_offer_description(pool: OfferPool, payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure PA clones use real shared-offer copy, never a generic placeholder."""
    current = str(payload.get('offerDesc') or payload.get('description') or '').strip()
    if not current or current == _PA_SOURCE_REBUILD_DESCRIPTION:
        current = _canonical_pa_offer_description(pool) or _PA_SOURCE_REBUILD_DESCRIPTION
    payload['offerDesc'] = current
    payload['description'] = current
    return payload


def _apply_pa_target_template(pool: OfferPool, payload: dict[str, Any]) -> dict[str, Any]:
    """Overlay the selected target's visible title and description on a PA clone.

    Target increases must not regenerate generic marketing text.  The current
    target listing is the source of truth; only the per-clone tracking suffix is
    changed immediately before posting.
    """
    listing = pool.listing
    raw = getattr(listing, 'raw_data', None) or {}
    stored_payload = raw.get('payload') if isinstance(raw.get('payload'), dict) else {}
    details = raw.get('details') if isinstance(raw.get('details'), dict) else {}

    title = str(
        getattr(listing, 'title', '')
        or raw.get('title')
        or stored_payload.get('title')
        or details.get('title')
        or ''
    ).strip()
    if title:
        payload['title'] = title

    description = str(
        stored_payload.get('offerDesc')
        or stored_payload.get('description')
        or raw.get('description')
        or details.get('offerDesc')
        or details.get('description')
        or ''
    ).strip()
    if not description or description == _PA_SOURCE_REBUILD_DESCRIPTION:
        description = _canonical_pa_offer_description(pool)
    if description:
        payload['offerDesc'] = description
        payload['description'] = description
    return payload


def _is_pa_relay_authorization_error(error: str) -> bool:
    """True when the relay reports a rejected marketplace session."""
    normalized = str(error or '').casefold()
    return 'unauthorized' in normalized or 'upstream_status=401' in normalized


class _PoolOfferContext:
    """Temporary compatibility facade for provider-specific legacy helpers.

    It keeps the large, battle-tested marketplace payload code intact while
    routing listing/config/monitoring access through PoolOffer.
    """

    _offer_fields = {
        'strategy', 'target_count', 'threshold', 'max_concurrent',
        'current_remote_count', 'last_checked_at', 'last_replenished_at',
        'last_error',
    }

    def __init__(self, pool_offer: PoolOffer):
        object.__setattr__(self, 'pool_offer', pool_offer)
        object.__setattr__(self, 'aggregate', pool_offer.pool)

    def __getattr__(self, name):
        if name in self._offer_fields:
            return getattr(self.pool_offer, name)
        if name == 'store':
            return self.pool_offer.store
        if name == 'store_id':
            return self.pool_offer.listing.integration_account_id
        if name == 'listing':
            return self.pool_offer.listing
        if name == 'listing_id':
            return self.pool_offer.listing_id
        if name == 'active_offers':
            return self.pool_offer.active_offers
        return getattr(self.aggregate, name)

    def __setattr__(self, name, value):
        if name in self._offer_fields:
            setattr(self.pool_offer, name, value)
        else:
            setattr(self.aggregate, name, value)

    def save(self, *, update_fields=None, **kwargs):
        requested = set(update_fields or [])
        offer_fields = requested & (self._offer_fields | {'updated_at'})
        aggregate_fields = requested - self._offer_fields
        if offer_fields:
            self.pool_offer.save(update_fields=list(offer_fields), **kwargs)
        if aggregate_fields - {'updated_at'}:
            self.aggregate.save(update_fields=list(aggregate_fields), **kwargs)


def _log(
    level: str,
    message: str,
    account: IntegrationAccount | None = None,
    detail: dict | None = None,
) -> None:
    PostingLog.objects.create(
        task_name=TASK_NAME,
        level=level,
        message=message[:255],
        detail=detail or {},
        integration_account=account,
    )


def replenish_pool_offer(pool_offer: PoolOffer) -> int:
    """Push claimed credentials to one linked marketplace offer."""
    pool_offer = PoolOffer.objects.select_related(
        'pool', 'pool__game', 'pool__credential_spec',
        'listing', 'listing__integration_account',
        'listing__integration_account__credential',
    ).get(pk=pool_offer.pk)
    if not pool_offer.can_replenish:
        return 0

    pool = _PoolOfferContext(pool_offer)
    marketplace = pool_offer.marketplace
    if marketplace == 'playerauctions':
        return _replenish_pa(pool)
    elif marketplace in ('eldorado', 'gameboost'):
        return _replenish_append(pool, marketplace)
    else:
        logger.warning('pool_replenish: unsupported marketplace %s for pool %d', marketplace, pool.pk)
        return 0


def replenish_pool(pool: OfferPool) -> int:
    """Compatibility wrapper: replenish all active linked offers for a pool."""
    if pool.status != OfferPoolStatus.ACTIVE:
        return 0
    return sum(
        replenish_pool_offer(pool_offer)
        for pool_offer in pool.pool_offers.all().order_by('pk')
    )


def _replenish_append(pool: OfferPool, marketplace: str) -> int:
    """Append credentials to existing offer (Eldorado / Gameboost)."""
    current_count = pool.current_remote_count or 0
    need = pool.target_count - current_count
    if need <= 0:
        # No append needed, but a GameBoost offer that sold out and reverted to
        # draft (then was restocked to target) would otherwise stay drafted
        # forever, since publish normally only runs after an append. Ensure a
        # drafted-but-stocked offer is (re)published.
        if marketplace == 'gameboost' and current_count > 0:
            _ensure_gameboost_published(pool)
        return 0

    store = pool.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        marketplace,
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    pending_items = claim_pending_items(pool.pool_offer, need)
    if not pending_items:
        _check_depleted(pool)
        return 0

    offer_id = pool.listing.store_listing_id
    pushed = 0

    try:
        if marketplace == 'eldorado':
            pushed = _push_eldorado(pool, client, offer_id, pending_items, proxy_group)
        elif marketplace == 'gameboost':
            pushed = _push_gameboost(pool, client, offer_id, pending_items, proxy_group)
    except Exception as exc:
        for item in pending_items:
            item.refresh_from_db(fields=['status'])
            if item.status == OfferPoolItemStatus.QUEUED:
                mark_item_failed(
                    item,
                    error_message=str(exc),
                    failure_stage='remote_push',
                    remote_state='unknown',
                )
        raise

    pool.last_replenished_at = timezone.now()
    pool.current_remote_count = (pool.current_remote_count or 0) + pushed
    pool.save(update_fields=['last_replenished_at', 'current_remote_count', 'updated_at'])

    _log(
        PostingLogLevel.SUCCESS if pushed > 0 else PostingLogLevel.WARNING,
        f"Pool #{pool.pk} replenished: {pushed}/{len(pending_items)} pushed to {marketplace}",
        account=store,
        detail={'pool_id': pool.pk, 'offer_id': offer_id, 'pushed': pushed, 'attempted': len(pending_items)},
    )

    _check_depleted(pool)
    return pushed


def _push_eldorado(
    pool: OfferPool,
    client: Any,
    offer_id: str,
    items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """Eldorado: fetch current creds, append new ones, update offer.

    On rate limit (429): delete offer, recreate with all creds, update listing.
    """
    # Fetch current credentials
    details_result = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
    if not details_result.ok:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: failed to fetch Eldorado credentials: {details_result.error}",
            account=pool.store,
            detail={'pool_id': pool.pk, 'offer_id': offer_id, 'error': str(details_result.error)},
        )
        release_claims_as_pending(items, 'Could not fetch Eldorado offer credentials')
        return 0

    # Build existing + new credential list
    existing_creds: list[str] = []
    resp = details_result.data
    if hasattr(resp, 'secretDetails') and resp.secretDetails:
        existing_creds = [entry.secretDetails for entry in resp.secretDetails if entry.secretDetails]
    elif hasattr(resp, 'accountsDetails') and resp.accountsDetails:
        existing_creds = [entry.secretDetails for entry in resp.accountsDetails if entry.secretDetails]

    new_creds: list[str] = []
    valid_items: list[OfferPoolItem] = []
    for item in items:
        try:
            cred_str = format_credential_for_marketplace(item.owned_product, 'eldorado', pool=pool)
            new_creds.append(cred_str)
            valid_items.append(item)
        except Exception as exc:
            mark_item_failed(
                item,
                error_message=str(exc),
                failure_stage='format',
                remote_state='absent',
            )

    if not new_creds:
        return 0

    all_creds = existing_creds + new_creds

    # Try update_offer with appended credentials
    update_payload = {'accountSecretDetails': all_creds}
    result = client.update_offer(offer_id, update_payload, proxy_group=proxy_group)

    if result.ok:
        remote_ids = _eldorado_remote_ids_for_credentials(
            client, offer_id, new_creds, proxy_group,
        )
        return _mark_items_pushed(
            valid_items,
            offer_id,
            listing=pool.listing,
            remote_credential_ids={
                item.pk: remote_ids[credential.strip()]
                for item, credential in zip(valid_items, new_creds)
                if remote_ids.get(credential.strip())
            },
        )

    # Update failed — fallback to delete + recreate strategy
    error_str = str(result.error) if result.error else ''
    status_code = getattr(result.error, 'status_code', None)
    _log(
        PostingLogLevel.WARNING,
        f"Pool #{pool.pk}: Eldorado update failed (HTTP {status_code}), falling back to recreate",
        account=pool.store,
        detail={'pool_id': pool.pk, 'old_offer_id': offer_id, 'error': error_str[:500]},
    )
    return _recreate_eldorado_offer(pool, client, all_creds, valid_items, proxy_group)


def _recreate_eldorado_offer(
    pool: OfferPool,
    client: Any,
    all_creds: list[str],
    new_items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """Create the replacement first, then best-effort delete the old offer."""
    listing = pool.listing
    old_offer_id = listing.store_listing_id

    # Get the original payload from listing.raw_data
    raw = listing.raw_data or {}
    original_payload = extract_create_payload(raw, 'eldorado')
    if not original_payload:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: cannot recreate — no original payload in listing.raw_data",
            account=pool.store,
        )
        for item in new_items:
            mark_item_failed(
                item,
                error_message='Eldorado source listing has no create payload',
                failure_stage='template',
                remote_state='absent',
            )
        return 0

    pushed = _create_eldorado_offer(
        pool, client, original_payload, all_creds, new_items, proxy_group,
    )
    if pushed <= 0:
        return 0

    delete_result = client.delete_offer(old_offer_id, proxy_group=proxy_group)
    if not delete_result.ok:
        _log(
            PostingLogLevel.WARNING,
            f"Pool #{pool.pk}: replacement created but old Eldorado offer "
            f"{old_offer_id} could not be deleted",
            account=pool.store,
            detail={
                'pool_id': pool.pk,
                'pool_offer_id': pool.pool_offer.pk,
                'old_offer_id': old_offer_id,
                'error': str(delete_result.error)[:500],
            },
        )
    return pushed


def _create_eldorado_offer(
    pool: OfferPool,
    client: Any,
    original_payload: dict[str, Any],
    all_creds: list[str],
    new_items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """Create a new Eldorado offer from original payload with given credentials.

    Used by both recreate (after delete) and recover (offer gone from remote).
    """
    listing = pool.listing
    old_offer_id = listing.store_listing_id

    create_payload = dict(original_payload)
    create_payload['accountSecretDetails'] = all_creds
    create_payload.setdefault('details', {}).setdefault('pricing', {})['quantity'] = len(all_creds)

    create_result = client.create_offer(create_payload, proxy_group=proxy_group)
    if not create_result.ok:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: failed to recreate offer: {create_result.error}",
            account=pool.store,
            detail={'pool_id': pool.pk, 'old_offer_id': old_offer_id},
        )
        release_claims_as_pending(new_items, 'Eldorado replacement create failed')
        return 0

    # Update listing with new offer ID
    new_offer_id = extract_listing_id(create_result.data)
    if not new_offer_id:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: Eldorado recreate succeeded but no offer ID in response",
            account=pool.store,
            detail={'pool_id': pool.pk, 'response': str(create_result.data)[:500]},
        )
        for item in new_items:
            mark_item_failed(
                item,
                error_message='Eldorado create succeeded but returned no offer ID',
                failure_stage='response_parse',
                remote_state='unknown',
            )
        return 0

    with transaction.atomic():
        listing.store_listing_id = new_offer_id
        listing.raw_data = normalize_offer_response(
            'eldorado',
            create_result.data,
            payload=create_payload,
        )
        listing.save(update_fields=['store_listing_id', 'raw_data', 'updated_at'])

        # Update pool's active offers if any
        OfferPoolActiveOffer.objects.filter(
            pool_offer=pool.pool_offer,
            store_listing_id=old_offer_id,
        ).update(store_listing_id=new_offer_id)

    _log(
        PostingLogLevel.SUCCESS,
        f"Pool #{pool.pk}: Eldorado offer recreated {old_offer_id} → {new_offer_id}",
        account=pool.store,
        detail={
            'pool_id': pool.pk,
            'old_offer_id': old_offer_id,
            'new_offer_id': new_offer_id,
            'total_creds': len(all_creds),
        },
    )

    remote_ids = _eldorado_remote_ids_for_credentials(
        client, new_offer_id, all_creds, proxy_group,
    )
    return _mark_items_pushed(
        new_items,
        new_offer_id,
        listing=pool.listing,
        remote_credential_ids={
            item.pk: remote_ids[credential.strip()]
            for item, credential in zip(new_items, all_creds[-len(new_items):])
            if remote_ids.get(credential.strip())
        },
    )


def _eldorado_remote_ids_for_credentials(
    client: Any,
    offer_id: str,
    credentials: list[str],
    proxy_group: str | None,
) -> dict[str, str]:
    """Return stable remote IDs for newly published Eldorado credentials.

    The post-update detail response is authoritative.  Failure is deliberately
    non-fatal: items are still pushed, but legacy text matching remains the
    fallback until the next successful identity-aware reconciliation.
    """
    details = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
    if not details.ok:
        logger.warning(
            'Pool Eldorado credential-ID fetch failed for offer %s: %s',
            offer_id,
            details.error,
        )
        return {}
    response = details.data
    entries = getattr(response, 'secretDetails', None) or getattr(
        response, 'accountsDetails', None,
    ) or []
    wanted = {credential.strip() for credential in credentials}
    return {
        str(getattr(entry, 'secretDetails', '')).strip(): str(getattr(entry, 'id', '')).strip()
        for entry in entries
        if str(getattr(entry, 'secretDetails', '')).strip() in wanted
        and str(getattr(entry, 'id', '')).strip()
    }


def _push_gameboost(
    pool: OfferPool,
    client: Any,
    offer_id: str,
    items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """Gameboost: detect format, then push credentials.

    Old format (login/password fields): delete offer → recreate with /account-offers/create
    New format (credentials array): use add_offer_credentials directly
    """
    # Format credentials first
    cred_strings: list[str] = []
    valid_items: list[OfferPoolItem] = []

    for item in items:
        try:
            cred_str = format_credential_for_marketplace(item.owned_product, 'gameboost', pool=pool)
            cred_strings.append(cred_str)
            valid_items.append(item)
        except Exception as exc:
            mark_item_failed(
                item,
                error_message=str(exc),
                failure_stage='format',
                remote_state='absent',
            )

    if not cred_strings:
        return 0

    # Detect offer format from DB payload — no remote call needed
    is_legacy = _is_gameboost_legacy_payload(pool.listing)

    if is_legacy:
        return _gameboost_recreate(pool, client, offer_id, cred_strings, valid_items, proxy_group)
    else:
        return _gameboost_add_credentials(pool, client, offer_id, cred_strings, valid_items, proxy_group)


def _gameboost_add_credentials(
    pool: OfferPool,
    client: Any,
    offer_id: str,
    cred_strings: list[str],
    valid_items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """New format: add credentials to existing multi-credential offer."""
    result = client.add_offer_credentials(offer_id, cred_strings, proxy_group=proxy_group)

    if not result.ok:
        error_str = str(result.error) if result.error else 'Unknown error'
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: Gameboost add_credentials failed: {error_str[:200]}",
            account=pool.store,
            detail={'pool_id': pool.pk, 'offer_id': offer_id, 'error': error_str[:500]},
        )
        for item in valid_items:
            mark_item_failed(
                item,
                error_message=f"API error: {error_str[:200]}",
                failure_stage='remote_push',
                remote_state='absent',
                retryable=True,
            )
        return 0

    # Fetch the authoritative credential list after add. This correctly handles
    # duplicate_count responses and records remote credential IDs without
    # assuming the API response order matches the request order.
    listed = client.list_offer_credentials(offer_id, proxy_group=proxy_group)
    if not listed.ok:
        for item in valid_items:
            mark_item_failed(
                item,
                error_message='GameBoost add returned success but credentials could not be reconciled',
                failure_stage='post_push_reconcile',
                remote_state='unknown',
            )
        return 0
    remote_by_text = {
        str(getattr(entry, 'credentials', '')).strip(): str(getattr(entry, 'id', ''))
        for entry in list(listed.data or [])
    }
    created_items: list[OfferPoolItem] = []
    missing_items: list[OfferPoolItem] = []
    remote_ids: dict[int, str] = {}
    for item, rendered in zip(valid_items, cred_strings):
        remote_id = remote_by_text.get(rendered.strip())
        if remote_id:
            created_items.append(item)
            remote_ids[item.pk] = remote_id
        else:
            missing_items.append(item)
    pushed = _mark_items_pushed(
        created_items,
        offer_id,
        listing=pool.listing,
        remote_credential_ids=remote_ids,
    )
    if missing_items:
        release_claims_as_pending(
            missing_items,
            'GameBoost did not create these credentials',
        )
    # A GameBoost offer that sold out can revert to draft/unpublished; appending
    # credentials does not re-list it. Publish after a successful restock so the
    # offer goes live again (no-op/ignored if already listed; non-fatal).
    if pushed > 0:
        _publish_gameboost_offer(client, offer_id, pool, proxy_group)
    return pushed


def _ensure_gameboost_published(pool: OfferPool) -> None:
    """Publish a GameBoost offer that has stock but is still in draft.

    Handles the no-append case (offer already at target credentials) where the
    offer nonetheless reverted to draft after selling out. Only publishes when
    the remote offer status is explicitly ``draft`` — a no-op otherwise, so it
    never re-lists an already-listed offer. Best-effort/non-fatal.
    """
    store = pool.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        'gameboost',
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )
    offer_id = pool.listing.store_listing_id
    try:
        res = client.get_offer(offer_id, proxy_group=proxy_group)
    except Exception as exc:
        logger.warning(
            'Pool #%d: GameBoost get_offer for publish-check failed for %s: %s',
            pool.pk, offer_id, exc,
        )
        return
    if not getattr(res, 'ok', False):
        return
    status = str(getattr(getattr(res, 'data', None), 'status', '') or '').strip().lower()
    if status == 'draft':
        _publish_gameboost_offer(client, offer_id, pool, proxy_group)


def _publish_gameboost_offer(
    client: Any,
    offer_id: str,
    pool: OfferPool,
    proxy_group: str | None,
) -> None:
    """(Re)publish a GameBoost offer after restock — best-effort, non-fatal.

    Mirrors the stock consumer's post-create list step so a drafted/unpublished
    offer becomes listed again once it has credentials.
    """
    try:
        result = client.list_account_offer(offer_id, proxy_group=proxy_group)
    except Exception as exc:
        logger.warning(
            'Pool #%d: GameBoost publish after restock error for offer %s: %s',
            pool.pk, offer_id, exc,
        )
        return
    if result is not None and hasattr(result, 'ok') and not result.ok:
        _log(
            PostingLogLevel.WARNING,
            f"Pool #{pool.pk}: GameBoost publish after restock failed for offer {offer_id}",
            account=pool.store,
            detail={
                'pool_id': pool.pk,
                'offer_id': offer_id,
                'error': str(getattr(result, 'error', ''))[:300],
            },
        )


def _gameboost_recreate(
    pool: OfferPool,
    client: Any,
    old_offer_id: str,
    cred_strings: list[str],
    valid_items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """Old format: create replacement first, then remove the legacy offer.

    Converts a single-credential offer to multi-credential format.
    """
    listing = pool.listing
    raw = listing.raw_data or {}
    original_payload = extract_create_payload(raw, 'gameboost')
    if not original_payload:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: cannot recreate Gameboost offer — no original payload in listing.raw_data",
            account=pool.store,
        )
        for item in valid_items:
            mark_item_failed(
                item,
                error_message='GameBoost source listing has no create payload',
                failure_stage='template',
                remote_state='absent',
            )
        return 0

    # Extract existing credential from old offer before deleting
    existing_creds = _extract_existing_gameboost_credentials(original_payload)

    # Build new payload: remove old single-credential fields, add credentials list
    # Preserve existing credential + append new ones
    all_creds = existing_creds + cred_strings
    create_payload = dict(original_payload)
    for field in ('login', 'password', 'email_login', 'email_password', 'email_provider', 'mail_provider'):
        create_payload.pop(field, None)
    create_payload['credentials'] = all_creds

    # Create new offer with multi-credential endpoint
    create_result = client.create_offer_with_credentials(create_payload, proxy_group=proxy_group)
    if not create_result.ok:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: failed to recreate Gameboost offer: {create_result.error}",
            account=pool.store,
            detail={'pool_id': pool.pk, 'old_offer_id': old_offer_id},
        )
        release_claims_as_pending(valid_items, 'GameBoost replacement create failed')
        return 0

    # Extract new offer ID
    new_offer_id = extract_listing_id(create_result.data)
    if not new_offer_id:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: Gameboost recreate succeeded but no offer ID in response",
            account=pool.store,
            detail={'pool_id': pool.pk, 'old_offer_id': old_offer_id, 'response': str(create_result.data)[:500]},
        )
        for item in valid_items:
            mark_item_failed(
                item,
                error_message='GameBoost create succeeded but returned no offer ID',
                failure_stage='response_parse',
                remote_state='unknown',
            )
        return 0

    delete_result = client.delete_offer(old_offer_id, proxy_group=proxy_group)
    if not delete_result.ok:
        _log(
            PostingLogLevel.WARNING,
            f"Pool #{pool.pk}: replacement created but old GameBoost offer "
            f"{old_offer_id} could not be deleted",
            account=pool.store,
            detail={
                'pool_id': pool.pk,
                'pool_offer_id': pool.pool_offer.pk,
                'old_offer_id': old_offer_id,
                'error': str(delete_result.error)[:500],
            },
        )

    with transaction.atomic():
        listing.store_listing_id = new_offer_id
        listing.raw_data = normalize_offer_response(
            'gameboost',
            create_result.data,
            payload=create_payload,
        )
        listing.save(update_fields=['store_listing_id', 'raw_data', 'updated_at'])

    _log(
        PostingLogLevel.SUCCESS,
        f"Pool #{pool.pk}: Gameboost offer recreated {old_offer_id} → {new_offer_id} (legacy → multi-cred)",
        account=pool.store,
        detail={
            'pool_id': pool.pk,
            'old_offer_id': old_offer_id,
            'new_offer_id': new_offer_id,
            'credentials_count': len(cred_strings),
        },
    )

    return _mark_items_pushed(valid_items, new_offer_id, listing=pool.listing)


def _replenish_pa(pool: OfferPool) -> int:
    """PlayerAuctions: fill to target_count without exceeding max_concurrent."""
    active_count = pool.active_offers.filter(
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).count()

    desired = min(pool.target_count, pool.max_concurrent)
    need = desired - active_count
    if need <= 0:
        return 0

    store = pool.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        'playerauctions',
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    # Prefer cloning the original payload when it is available.  Some legacy
    # source listings, however, were adopted without their create payload.
    # For those lanes, rebuild from the pending owned product through the normal
    # stock pipeline rather than permanently disabling or starving the lane.
    raw = pool.listing.raw_data or {}
    original_payload = extract_create_payload(
        raw,
        'playerauctions',
        client=client,
        proxy_group=proxy_group,
    )

    pending_items = claim_pending_items(pool.pool_offer, need)
    if not pending_items:
        _check_depleted(pool)
        return 0

    pushed = 0
    for item in pending_items:
        try:
            if original_payload:
                pushed += _clone_pa_offer(
                    pool, client, original_payload, item, proxy_group,
                )
            else:
                pushed += _rebuild_pa_offer_from_stock(
                    pool, client, item, proxy_group,
                )
        except Exception as exc:
            logger.exception('pool_replenish: PA replacement failed for item %d', item.pk)
            mark_item_failed(
                item,
                error_message=str(exc),
                failure_stage='remote_push',
                remote_state='unknown',
            )

    pool.last_replenished_at = timezone.now()
    pool.current_remote_count = active_count + pushed
    pool.save(update_fields=[
        'last_replenished_at', 'current_remote_count', 'updated_at',
    ])

    source = 'cloned' if original_payload else 'rebuilt from stock'
    _log(
        PostingLogLevel.SUCCESS if pushed > 0 else PostingLogLevel.WARNING,
        f"Pool #{pool.pk} PA replenish: {pushed}/{len(pending_items)} {source}",
        account=store,
        detail={
            'pool_id': pool.pk,
            'pushed': pushed,
            'attempted': len(pending_items),
            'source_rebuild': not bool(original_payload),
        },
    )

    _check_depleted(pool)
    return pushed


def _source_key_for_owned_product(product: Any) -> str:
    """Return the configured source key for one persisted owned product."""
    raw = getattr(product, 'raw_data', None) or {}
    if raw.get('source') == 'manual':
        return 'manual'
    if raw.get('source') == 'tracker_sheet':
        return 'tracker_sheet'
    source_account = getattr(product, 'source_account', None)
    if source_account and source_account.provider:
        return source_account.provider
    return str(raw.get('source') or '')


def _rebuild_pa_offer_from_stock(
    pool: OfferPool,
    client: Any,
    item: OfferPoolItem,
    proxy_group: str | None,
) -> int:
    """Build and post a PA replacement from owned stock when no clone payload exists.

    This is intentionally limited to the current claimed item.  It uses the
    same prepare/build path as normal stock posting and overrides only the
    computed price with the pool offer's established selling price.
    """
    product = item.owned_product
    raw = getattr(product, 'raw_data', None) or {}
    if not isinstance(raw, dict) or not raw:
        raise ValueError('PlayerAuctions source rebuild requires owned-product source data')

    source_key = _source_key_for_owned_product(product)
    if not source_key:
        raise ValueError('PlayerAuctions source rebuild requires a configured source key')

    prepared_result = adapter.prepare(
        game_slug=pool.game.slug,
        sources={source_key: raw},
        kind=ListingKind.STOCK,
        disable_media=True,
        ref_key=product.ref_key or '',
    )
    if not prepared_result.success:
        raise ValueError(
            'PlayerAuctions source rebuild prepare failed: '
            f"{prepared_result.error_stage or 'prepare'}: "
            f"{prepared_result.error or 'unknown error'}"
        )

    variant_context = build_variant_context(
        store=pool.store,
        game=pool.game,
        marketplace='playerauctions',
    )
    router = VariantRouter(variant_context, mode='stock')
    main_platform = getattr(prepared_result.prepared.subject, 'main_platform', '') or ''
    variant_slug = router.select_fixed('platform', main_platform) if main_platform else ''

    # Use the direct JSON builder rather than the bulk-row builder.  The
    # direct builder carries GTA's numeric serverId/categoryId values, which
    # the PA relay requires for a single-offer replacement.
    build_result = adapter.build(
        prepared=prepared_result.prepared,
        marketplace='playerauctions',
        pricing_defaults=STOCK_PRICING_BASELINE,
        store=pool.store,
        game=pool.game,
        kind=ListingKind.STOCK,
        variant_slug=variant_slug,
        variant_context=variant_context,
    )
    if not build_result.success:
        raise ValueError(
            'PlayerAuctions source rebuild failed: '
            f"{build_result.error_stage or 'build'}: "
            f"{build_result.error or 'unknown error'}"
        )

    payload = dict(build_result.payload or {})
    if not payload:
        raise ValueError('PlayerAuctions source rebuild returned an empty JSON payload')
    _apply_pa_target_template(pool, payload)
    if pool.listing.price is not None:
        payload['price'] = round(float(pool.listing.price), 2)
    _ensure_pa_offer_description(pool, payload)

    return _post_pa_excel_row(
        pool,
        client,
        item,
        payload,
        proxy_group,
        variant_slug=variant_slug,
    )


def _clone_pa_offer(
    pool: OfferPool,
    client: Any,
    original_payload: dict,
    item: OfferPoolItem,
    proxy_group: str | None,
) -> int:
    """Create a single PA clone offer with new credentials."""
    payload = dict(original_payload)
    _apply_pa_target_template(pool, payload)

    # Replace credentials with platform-aware format
    product = item.owned_product
    _apply_pa_auto_delivery_credentials(payload, product, pool=pool)

    # Build Excel-row dict from the legacy create payload, then use the same
    # relay persistence path as a source-driven replacement.
    return _post_pa_excel_row(
        pool,
        client,
        item,
        _build_excel_row_from_payload(payload),
        proxy_group,
        raw_payload=payload,
    )


def _post_pa_excel_row(
    pool: OfferPool,
    client: Any,
    item: OfferPoolItem,
    excel_row: dict[str, Any],
    proxy_group: str | None,
    *,
    variant_slug: str = '',
    raw_payload: dict[str, Any] | None = None,
) -> int:
    """Post one prepared PA bulk row and atomically persist its pool clone."""
    tracking_code = pool_clone_tracking_code(pool.aggregate, item, item.claim_token)
    title_key = 'Title' if 'Title' in excel_row or 'title' not in excel_row else 'title'
    excel_row = dict(excel_row)
    excel_row[title_key] = append_tracking_code_for_code(
        excel_row.get(title_key, '') or pool.listing.title,
        tracking_code,
    )
    if raw_payload is not None:
        raw_payload = dict(raw_payload)
        raw_payload['title'] = excel_row[title_key]

    store_credentials = (
        getattr(pool.listing.integration_account.credential, 'credentials', None) or {}
        if getattr(pool.listing.integration_account, 'credential', None)
        else {}
    )
    username = store_credentials.get('username', '')
    password = store_credentials.get('password', '')
    store_slug = store_credentials.get('store_slug', '')
    relay_url = store_credentials.get('relay_url', 'http://35.196.132.30:3001')
    relay_secret = store_credentials.get('relay_secret', 'pa-relay-secret-2026')
    token = store_credentials.get('access_token', '')
    cookie = store_credentials.get('cookie', '')

    if not token and username and password and store_slug:
        token, cookie = fetch_relay_token(
            username,
            password,
            store_slug,
            relay_url=relay_url,
            relay_secret=relay_secret,
        )
    if not token:
        mark_item_failed(
            item,
            error_message='PA relay: could not obtain access token for pool replacement',
            failure_stage='remote_push',
            remote_state='absent',
            retryable=True,
        )
        return 0

    relay_poster = PARelayPoster(
        relay_url=relay_url,
        relay_secret=relay_secret,
    )
    relay_result = relay_poster.post_batch(
        token,
        store_slug,
        [excel_row],
        cookie=(cookie or token),
    )
    if (
        0 in relay_result.failed
        and _is_pa_relay_authorization_error(relay_result.failed[0])
        and username
        and password
        and store_slug
    ):
        logger.info(
            'PA relay rejected the stored session; forcing one fresh browser session for pool offer %s',
            pool.pk,
        )
        fresh_token, fresh_cookie = fetch_relay_token(
            username,
            password,
            store_slug,
            relay_url=relay_url,
            relay_secret=relay_secret,
            force_refresh=True,
        )
        if fresh_token:
            relay_result = relay_poster.post_batch(
                fresh_token,
                store_slug,
                [excel_row],
                cookie=(fresh_cookie or fresh_token),
            )
    if 0 in relay_result.failed:
        error_str = relay_result.failed[0]
        mark_item_failed(
            item,
            error_message=f"PA relay replacement failed: {error_str[:200]}",
            failure_stage='remote_push',
            remote_state='absent',
            retryable=True,
        )
        return 0

    new_offer_id = relay_result.successful.get(0, '')
    if not new_offer_id:
        mark_item_failed(
            item,
            error_message='PA relay replacement succeeded but no offer ID returned',
            failure_stage='response_parse',
            remote_state='unknown',
        )
        return 0

    persisted_payload = raw_payload or excel_row
    raw_data = normalize_offer_response(
        'playerauctions',
        {'offer_id': new_offer_id},
        payload=persisted_payload,
        client=client,
        proxy_group=proxy_group,
    )
    listing_variant = pool.listing.variant
    if variant_slug:
        listing_variant = (
            GameVariant.objects.filter(game=pool.game, slug=variant_slug).first()
            or listing_variant
        )

    with transaction.atomic():
        new_listing = Listing.objects.create(
            is_instant=True,
            integration_account=pool.store,
            game=pool.game,
            store_listing_id=new_offer_id,
            variant=listing_variant,
            title=(excel_row.get('Title') or excel_row.get('title') or pool.listing.title),
            price=pool.listing.price,
            currency=pool.listing.currency,
            raw_data=raw_data,
        )
        ListingOwnedProduct.objects.create(
            listing=new_listing,
            owned_product=item.owned_product,
        )
        OfferPoolActiveOffer.objects.create(
            pool=pool.aggregate,
            pool_offer=pool.pool_offer,
            store_listing_id=new_offer_id,
            listing=new_listing,
            pool_item=item,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        )
        finalize_items_pushed(
            [item],
            pool_offer=pool.pool_offer,
            remote_offer_id=new_offer_id,
        )

    return 1


def _apply_pa_auto_delivery_credentials(
    payload: dict,
    product: Any,
    pool: OfferPool | None = None,
) -> None:
    """Apply PA autoDelivery credentials — spec-driven with legacy fallback."""
    from .spec_resolver import resolve_spec

    spec = resolve_spec(pool) if pool else None
    auto_delivery = dict(payload.get('autoDelivery') or {})

    if spec:
        # Spec-driven: render PA dict template
        pa_template = (spec.format_templates or {}).get('playerauctions')
        if isinstance(pa_template, dict):
            context = build_credential_render_context(product, spec)
            rendered = render_template(pa_template, context)

            auto_delivery['loginName'] = rendered.get('loginName', '')
            auto_delivery['password'] = rendered.get('password', '')
            auto_delivery['instruction'] = rendered.get('instruction', '')

            # Always overwrite retype from final values
            auto_delivery['retypeLoginName'] = auto_delivery['loginName']
            auto_delivery['retypePassword'] = auto_delivery['password']

            owner_email = rendered.get('ownerEmail', '')
            if owner_email:
                for owner_key in ('original', 'current'):
                    owner = auto_delivery.get(owner_key)
                    if isinstance(owner, dict):
                        owner = dict(owner)
                        owner['email'] = owner_email
                        auto_delivery[owner_key] = owner
        else:
            # Spec exists but no PA template — use instruction from string render
            instruction = format_credential_by_spec(product, spec, 'playerauctions')
            if isinstance(instruction, dict):
                instruction = instruction.get('instruction', '')
            from .spec_resolver import build_field_role_map
            role_map = build_field_role_map(spec)
            context = build_credential_render_context(product, spec)
            login_val = context.get(role_map.get('login', 'login'), '')
            pass_val = context.get(role_map.get('password', 'password'), '')

            auto_delivery['loginName'] = login_val
            auto_delivery['password'] = pass_val
            auto_delivery['retypeLoginName'] = login_val
            auto_delivery['retypePassword'] = pass_val
            auto_delivery['instruction'] = instruction
    else:
        # Legacy fallback
        bundle = build_credential_bundle(product)
        auto_delivery.update({
            'loginName': bundle.login,
            'retypeLoginName': bundle.login,
            'password': bundle.password,
            'retypePassword': bundle.password,
            'instruction': format_credential_for_marketplace(product, 'playerauctions'),
        })

        if bundle.email_login:
            for owner_key in ('original', 'current'):
                owner = auto_delivery.get(owner_key)
                if isinstance(owner, dict):
                    owner = dict(owner)
                    owner['email'] = bundle.email_login
                    auto_delivery[owner_key] = owner

    payload['autoDelivery'] = auto_delivery


# ── Helpers ───────────────────────────────────────────────────────


def _is_gameboost_legacy_payload(listing: Any) -> bool:
    """Detect Gameboost offer format from DB payload — no API call needed.

    Legacy: listing.raw_data.payload has 'login' field (single-credential).
    New:    listing.raw_data.payload has 'credentials' list (multi-credential).
    """
    raw = getattr(listing, 'raw_data', None) or {}
    if raw.get('_credential_entries'):
        return False

    payload = raw.get('payload')
    if isinstance(payload, dict):
        if payload.get('credentials'):
            return False
        if payload.get('login'):
            return True

    credentials = raw.get('credentials')
    if isinstance(credentials, dict):
        return bool(credentials.get('login'))

    return False


def _extract_existing_gameboost_credentials(payload: dict) -> list[str]:
    credentials = payload.get('credentials')
    if isinstance(credentials, list):
        return [str(credential) for credential in credentials if credential]

    legacy = _extract_legacy_gameboost_credential(payload)
    return [legacy] if legacy else []


def _extract_legacy_gameboost_credential(payload: dict) -> str | None:
    """Build a credential string from old-format payload fields (login/password/email)."""
    login = payload.get('login', '')
    password = payload.get('password', '')
    if not login or not password:
        return None

    parts: list[str] = [f"Login: {login}", f"Password: {password}"]
    if payload.get('email_login'):
        parts.append(f"Email: {payload['email_login']}")
    if payload.get('email_password'):
        parts.append(f"Email Password: {payload['email_password']}")
    return "\n".join(parts)


def _reconcile_pushed_items(
    pool: OfferPool,
    remote_creds: list[str],
    *,
    remote_credential_ids: set[str] | None = None,
) -> int:
    """Mark only credentials proven absent from the remote offer as consumed.

    Prefer the immutable remote credential ID recorded when an item was pushed.
    Rendering account details again is a compatibility fallback for historical
    items without an ID because formatting rules and source data can change
    after the credential was successfully published.
    """
    pushed_items = list(
        pool.items.filter(
            status=OfferPoolItemStatus.PUSHED,
            pool_offer=pool.pool_offer,
        )
        .select_related('owned_product')
    )
    if not pushed_items:
        return 0

    marketplace = pool.store.provider
    consumed = 0
    remote_id_set = {
        str(remote_id).strip()
        for remote_id in (remote_credential_ids or set())
        if str(remote_id).strip()
    }

    for item in pushed_items:
        if item.remote_credential_id and remote_id_set:
            found = item.remote_credential_id.strip() in remote_id_set
        else:
            try:
                expected_cred = format_credential_for_marketplace(
                    item.owned_product, marketplace, pool=pool,
                )
            except Exception:
                continue

            if isinstance(expected_cred, dict):
                # PA dict format — not applicable here
                continue

            # Normalize whitespace for the legacy historical fallback only.
            expected_norm = expected_cred.strip()
            found = any(rc.strip() == expected_norm for rc in remote_creds)

        if not found:
            item.status = OfferPoolItemStatus.CONSUMED
            item.consumed_at = timezone.now()
            item.remote_state = 'absent'
            item.error_message = 'Removed from remote offer'
            item.save(update_fields=[
                'status', 'consumed_at', 'remote_state', 'error_message', 'updated_at',
            ])

            # Unlink from listing and revert OwnedProduct status
            if pool.listing_id and item.owned_product_id:
                ListingOwnedProduct.objects.filter(
                    listing_id=pool.listing_id,
                    owned_product_id=item.owned_product_id,
                ).delete()
                owned = item.owned_product
                if owned.status == 'listed':
                    owned.status = 'draft'
                    owned.save(update_fields=['status', 'updated_at'])

            consumed += 1

    if consumed > 0:
        _log(
            PostingLogLevel.INFO,
            f"Pool #{pool.pk}: reconciled {consumed} item(s) as CONSUMED (no longer on remote)",
            account=pool.store,
            detail={'pool_id': pool.pk, 'consumed': consumed},
        )

    return consumed


def _mark_items_pushed(
    items: list[OfferPoolItem],
    offer_id: str,
    listing: Listing | None = None,
    remote_credential_ids: dict[int, str] | None = None,
) -> int:
    """Mark items as PUSHED, record target offer ID, and link OwnedProducts to Listing."""
    if not items:
        return 0
    pool_offer = items[0].pool_offer
    if pool_offer is None:
        raise ValueError('Cannot finalize unassigned pool items')
    queued_items = [
        item for item in items if item.status == OfferPoolItemStatus.QUEUED
    ]
    already_pushed = [
        item for item in items if item.status == OfferPoolItemStatus.PUSHED
    ]
    count = finalize_items_pushed(
        queued_items,
        pool_offer=pool_offer,
        remote_offer_id=offer_id,
        remote_credential_ids=remote_credential_ids,
    )
    count += len(already_pushed)

    for item in items:
        item.refresh_from_db(fields=['status'])
        if item.status != OfferPoolItemStatus.PUSHED:
            continue
        # Create m2m link → triggers signal: OwnedProduct draft → listed
        if listing and item.owned_product_id:
            _, created = ListingOwnedProduct.objects.get_or_create(
                listing=listing,
                owned_product=item.owned_product,
            )
            # If link already existed, signal didn't fire — fix status manually
            if not created:
                owned = item.owned_product
                if owned.status == 'draft':
                    owned.status = 'listed'
                    owned.save(update_fields=['status', 'updated_at'])

    return count


def _check_depleted(pool: OfferPool) -> None:
    """Depletion is computed health; never overwrite user intent state."""
    return None

def _build_excel_row_from_payload(payload: dict) -> dict:
    """Convert a PA JSON offer payload back to an Excel-row-style dict for PARelayPoster.

    PARelayPoster._build_json_payload() expects Excel column names.
    This function reverses that mapping so pool replenisher can use PARelayPoster
    without needing to rebuild the full Excel row from scratch.
    """
    auto_delivery = payload.get('autoDelivery') or {}
    manual = payload.get('manual') or {}
    return {
        'Game': payload.get('gameId', ''),
        'Server': payload.get('serverId', ''),
        'Title': payload.get('title', ''),
        'Description': payload.get('offerDesc', ''),
        'Price': payload.get('price', 0),
        'Offer Duration': payload.get('offerDuration', 30),
        'Seller After-Sale Protection': payload.get('freeInsurance', 7),
        'Cover image (PA hosted)': payload.get('screenShot', ''),
        'Auto Delivery': 'Yes' if payload.get('isAuto') else 'No',
        # Auto delivery credentials
        'Login': auto_delivery.get('loginName', ''),
        'Password': auto_delivery.get('password', ''),
        'Instruction': auto_delivery.get('instruction', ''),
        'Registration CD Key': auto_delivery.get('firstCDKey', ''),
        # Pass through the full autoDelivery dict for PARelayPoster to use
        '_autoDelivery': auto_delivery,
        '_payload': payload,  # full original payload passthrough
    }
