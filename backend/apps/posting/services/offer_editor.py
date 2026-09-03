"""Offer editor — update title / description / price on marketplace.

Supports three strategies:
- Eldorado: PUT update_offer directly
- GameBoost: PATCH update_offer directly
- PlayerAuctions: cancel_offers + bulk_upload (single or pool-wide)
"""
from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolDispatchAttempt,
    PoolDispatchOperation,
    PoolDispatchStatus,
    PostingLog,
    PostingLogLevel,
)
from apps.posting.services.pool.formatter import build_credential_bundle
from apps.posting.services.stock.pa_relay_poster import PARelayPoster, fetch_relay_token
from apps.posting.services.stock.pa_tracking import (
    append_tracking_code_for_code,
    extract_tracking_code,
    pool_clone_tracking_code,
)
from core.marketplace.normalizers import normalize_offer_response

logger = logging.getLogger(__name__)

TASK_NAME = 'offer_edit'

# PA payload field names (must match PlayerAuctionsMapper.build_from_raw output)
_PA_TITLE = 'title'
_PA_DESC  = 'offerDesc'
_PA_PRICE = 'price'


# ── Result types ──────────────────────────────────────────────────

@dataclass
class EditResult:
    ok: bool = True
    error: str = ''
    new_offer_id: str = ''
    new_tracking_code: str = ''
    queue_request_id: int | None = None


@dataclass
class BulkEditResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ── Logging helper ────────────────────────────────────────────────

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


# ── Public API ────────────────────────────────────────────────────

def edit_offer(listing: Listing, changes: dict[str, Any]) -> EditResult:
    """Edit a single listing on the marketplace and update local DB.

    changes may contain: title, description, price
    """
    store = listing.integration_account
    if not store:
        return EditResult(ok=False, error='Listing has no integration account')

    provider_name = store.provider
    try:
        if provider_name == 'eldorado':
            return _edit_eldorado(listing, changes, store)
        elif provider_name == 'gameboost':
            return _edit_gameboost(listing, changes, store)
        elif provider_name == 'playerauctions':
            return _edit_pa_single(listing, changes, store)
        else:
            return EditResult(ok=False, error=f'Unsupported marketplace: {provider_name}')
    except Exception as exc:
        logger.exception('offer_edit: failed for listing %d', listing.pk)
        _log(PostingLogLevel.ERROR, f'Edit failed for listing #{listing.pk}: {exc}', account=store)
        return EditResult(ok=False, error=str(exc)[:500])


def edit_pool_offer(pool_offer: PoolOffer, changes: dict[str, Any]) -> EditResult:
    """Edit one configured marketplace target from the pool-detail panel."""
    if pool_offer.strategy == OfferPool.Strategy.CLONE:
        from apps.posting.services.pool.replenisher import _PoolOfferContext

        bulk = _queue_pa_pool_bulk(_PoolOfferContext(pool_offer), changes)
        return EditResult(
            ok=bulk.failed == 0,
            error='; '.join(error for error in bulk.errors if error)[:500],
        )
    return edit_offer(pool_offer.listing, changes)


def relist_pa_pool_item(item: OfferPoolItem) -> EditResult:
    """Bump one PlayerAuctions account while preserving its existing trace code.

    The action is deliberately narrow: it accepts only a pushed item with one
    active PA clone, validates all local linkage before the remote cancellation,
    and delegates the replacement handoff to ``_edit_pa_single``.  Successful
    handoff preserves the exact Pool item, clone, title code, and price while
    recording only PA's replacement offer ID and fresh lifecycle dates.
    """
    if item.status != OfferPoolItemStatus.PUSHED:
        return EditResult(
            ok=False,
            error=f'Only a pushed PlayerAuctions account can be relisted (current status: {item.status}).',
        )
    if not item.pool_offer_id or item.pool_offer.marketplace != 'playerauctions':
        return EditResult(ok=False, error='This account is not assigned to a PlayerAuctions offer.')

    relistable_clones = list(
        OfferPoolActiveOffer.objects.filter(
            pool_item=item,
            pool_offer=item.pool_offer,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        ).select_related('listing', 'listing__integration_account', 'pool__game')
    )
    if len(relistable_clones) != 1:
        return EditResult(
            ok=False,
            error=(
                'Expected exactly one live PlayerAuctions clone for this account; '
                f'found {len(relistable_clones)}. No marketplace action was taken.'
            ),
        )

    active_clone = relistable_clones[0]
    listing = active_clone.listing
    store = getattr(listing, 'integration_account', None) if listing else None
    if not listing or not store or store.provider != 'playerauctions':
        return EditResult(ok=False, error='Active clone has no valid PlayerAuctions listing link.')
    if listing.status not in (
        ListingStatus.LISTED,
        ListingStatus.PAUSED,
        ListingStatus.CLOSED,
        ListingStatus.DELETED,
    ):
        return EditResult(
            ok=False,
            error=f'Active clone listing is not relistable (current status: {listing.status}).',
        )

    try:
        tracking_code, title = _bump_title_with_existing_tracking_code(listing, item)
    except ValueError as exc:
        return EditResult(ok=False, error=str(exc))

    from apps.posting.services.pa_edit_queue import enqueue_pa_edit

    request = enqueue_pa_edit(
        listing=listing,
        changes={},
        pool_offer=item.pool_offer,
        pool_item=item,
        active_offer=active_clone,
    )
    return EditResult(
        ok=True,
        new_tracking_code=tracking_code,
        queue_request_id=request.pk,
    )


def _queue_pa_pool_bulk(pool: Any, changes: dict[str, Any]) -> BulkEditResult:
    """Queue one same-offer PA update per current active clone, globally serial."""
    from apps.posting.services.pa_edit_queue import enqueue_pa_edit

    active_clones = list(
        OfferPoolActiveOffer.objects.filter(
            pool_offer=pool.pool_offer,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        ).select_related('listing', 'pool_item')
    )
    if not active_clones:
        return BulkEditResult(
            total=0,
            failed=1,
            errors=['No current PlayerAuctions offer is available to queue for update.'],
        )

    queued = 0
    errors = []
    for clone in active_clones:
        if not clone.listing_id or not clone.pool_item_id:
            errors.append(f'Clone {clone.pk} is missing listing or pool-item linkage.')
            continue
        enqueue_pa_edit(
            listing=clone.listing,
            changes=changes,
            pool_offer=pool.pool_offer,
            pool_item=clone.pool_item,
            active_offer=clone,
        )
        queued += 1
    return BulkEditResult(
        total=len(active_clones),
        succeeded=queued,
        failed=len(errors),
        errors=errors,
    )


def _bump_title_with_existing_tracking_code(
    listing: Listing,
    item: OfferPoolItem,
) -> tuple[str, str]:
    """Keep an account’s durable PA code exactly unchanged during a bump."""
    product = getattr(item, 'owned_product', None)
    tracking_code = extract_tracking_code(
        getattr(listing, 'title', ''),
        getattr(product, 'ref_key', ''),
    )
    if not tracking_code:
        raise ValueError(
            'This account has no existing PlayerAuctions unique code, so Bump PA Offer is blocked. '
            'Add the correct code first rather than generating a different one.'
        )
    try:
        title = append_tracking_code_for_code(
            listing.title or '',
            tracking_code,
        )
    except ValueError as exc:
        raise ValueError(
            f'The existing PlayerAuctions unique code cannot be preserved safely: {exc}'
        ) from exc
    return tracking_code, title


def edit_pool_offers(pool: OfferPool, changes: dict[str, Any]) -> BulkEditResult:
    """Compatibility bulk edit across every linked offer in the pool."""
    from apps.posting.services.pool.replenisher import _PoolOfferContext

    aggregate = BulkEditResult()
    pool_offers = pool.pool_offers.select_related(
        'pool', 'listing', 'listing__integration_account',
    ).order_by('pk')
    for pool_offer in pool_offers:
        if pool_offer.strategy == OfferPool.Strategy.CLONE:
            result = _queue_pa_pool_bulk(_PoolOfferContext(pool_offer), changes)
        else:
            edited = edit_offer(pool_offer.listing, changes)
            result = BulkEditResult(total=1)
            if edited.ok:
                result.succeeded = 1
            else:
                result.failed = 1
                result.errors.append(edited.error)
        aggregate.total += result.total
        aggregate.succeeded += result.succeeded
        aggregate.failed += result.failed
        aggregate.errors.extend(result.errors)
    return aggregate


# ── Eldorado ──────────────────────────────────────────────────────

def _edit_eldorado(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    """Edit an Eldorado listing via PUT /api/flexibleOffers/account/{id}/details."""
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client('eldorado', store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group)

    offer_id = listing.store_listing_id
    raw = listing.raw_data or {}

    # Prefer authoritative managed pool credentials so every new/recreated
    # Eldorado entry contains login, password, email, and email password.
    account_secret_details = _managed_eldorado_secret_entries(listing)
    if not account_secret_details:
        # Legacy fallback: read the provider entry, then persisted canonical text.
        creds_result = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
        if creds_result.ok and creds_result.data:
            resp = creds_result.data
            src = resp.accountsDetails or resp.secretDetails or []
            account_secret_details = [e.secretDetails for e in src if e.secretDetails]
    if not account_secret_details:
        account_secret_details = [
            e['secretDetails']
            for e in (raw.get('_credential_entries') or [])
            if e.get('secretDetails')
        ]

    # Build details block — apply changes on top of raw_data values
    raw_price = raw.get('pricePerUnit') or {}
    details: dict[str, Any] = {
        'pricing': {
            'quantity': len(account_secret_details) or raw.get('quantity', 1),
            'minQuantity': raw.get('minQuantity', 1),
            'pricePerUnit': {
                'amount': float(changes['price']) if 'price' in changes else float(raw_price.get('amount', 0)),
                'currency': raw_price.get('currency', 'USD'),
            },
            'volumeDiscounts': raw.get('volumeDiscounts') or [],
        },
        'offerTitle': changes.get('title', raw.get('offerTitle', '')),
        'description': changes.get('description', raw.get('description', '')),
        'guaranteedDeliveryTime': raw.get('guaranteedDeliveryTime', 'Instant'),
        'hasOriginalEmail': raw.get('hasOriginalEmail') or False,
        'mainOfferImage': raw.get('mainOfferImage') or {},
        'offerImages': raw.get('offerImages') or [],
    }

    # Build augmentedGame block from flat raw_data
    trade_envs = raw.get('tradeEnvironmentValues') or []
    trade_env_id = str(trade_envs[0]['id']) if trade_envs and trade_envs[0].get('id') is not None else None
    raw_attrs = raw.get('attributes') or []
    offer_attributes = [
        {'id': a.get('id', ''), 'type': 'Select', 'value': (a.get('value') or {}).get('id', '')}
        for a in raw_attrs
    ]
    augmented_game: dict[str, Any] = {
        'gameId': str(raw.get('gameId', '')),
        'category': raw.get('category', 'Account'),
        'tradeEnvironmentId': trade_env_id,
        'offerAttributes': offer_attributes,
        'attributeIdsCsv': None,
    }

    payload: dict[str, Any] = {
        'details': details,
        'augmentedGame': augmented_game,
        'accountSecretDetails': account_secret_details,
    }

    provider = get_provider('eldorado')
    result = provider.update_listing(client, offer_id, payload)

    if not (result and getattr(result, 'ok', True)):
        error_msg = str(getattr(result, 'error', 'Unknown error'))
        if _is_eldorado_legacy_edit_error(error_msg):
            recreated = _recreate_eldorado_offer(
                listing,
                changes,
                payload,
                client=client,
                provider=provider,
                proxy_group=proxy_group,
            )
            if recreated.ok:
                _log(
                    PostingLogLevel.SUCCESS,
                    f'Eldorado legacy listing #{listing.pk} recreated for edit',
                    account=store,
                    detail={
                        'listing_id': listing.pk,
                        'old_offer_id': offer_id,
                        'new_offer_id': recreated.new_offer_id,
                        'changes': list(changes.keys()),
                    },
                )
                return recreated
            error_msg = recreated.error or error_msg
        _log(PostingLogLevel.ERROR,
             f'Eldorado edit failed for #{listing.pk}: {error_msg}',
             account=store,
             detail={'listing_id': listing.pk, 'offer_id': offer_id})
        return EditResult(ok=False, error=error_msg)

    _update_listing_db(listing, changes)
    _log(PostingLogLevel.SUCCESS,
         f'Listing #{listing.pk} edited on Eldorado',
         account=store,
         detail={'listing_id': listing.pk, 'offer_id': offer_id, 'changes': list(changes.keys())})
    return EditResult(ok=True)


def _managed_eldorado_secret_entries(listing: Listing) -> list[str]:
    """Build canonical structured credential strings from linked managed stock."""
    products = []
    for link in ListingOwnedProduct.objects.filter(listing=listing).select_related('owned_product').order_by('pk'):
        products.append(link.owned_product)
    if not products:
        for active in OfferPoolActiveOffer.objects.filter(listing=listing).select_related('pool_item__owned_product').order_by('pk'):
            if active.pool_item and active.pool_item.owned_product:
                products.append(active.pool_item.owned_product)
    entries: list[str] = []
    seen_ids: set[int] = set()
    for product in products:
        if product.pk in seen_ids:
            continue
        seen_ids.add(product.pk)
        entry = build_credential_bundle(product).to_eldorado_account_secret()
        if entry:
            entries.append(entry)
    return entries


def _is_eldorado_legacy_edit_error(error: str) -> bool:
    """Recognize Eldorado's explicit legacy-entry edit rejection only."""
    text = str(error or '').lower()
    return (
        'legacy account entry' in text
        or ('structured details' in text and 'creation flow' in text)
    )


def _recreate_eldorado_offer(
    listing: Listing,
    changes: dict[str, Any],
    payload: dict[str, Any],
    *,
    client: Any,
    provider: Any,
    proxy_group: str | None,
) -> EditResult:
    """Create a replacement offer first, delete the old offer, then hand off local links.

    Eldorado legacy offers reject structured edits.  Creation is performed before
    deletion so a failed create never destroys the current listing.  The local
    Listing/PoolOffer handoff happens only after the new offer exists and the old
    offer has been deleted successfully.
    """
    from apps.posting.services.relist import _extract_offer_id, _replace_in_db

    product_data: dict[str, Any] = {'payload': payload}
    if proxy_group:
        product_data['proxy_group'] = proxy_group
    try:
        created = provider.create_listing(client, product_data)
    except Exception as exc:
        return EditResult(ok=False, error=f'Legacy offer recreation create failed: {exc}')

    if not created or not getattr(created, 'ok', True):
        return EditResult(
            ok=False,
            error=f'Legacy offer recreation create failed: {getattr(created, "error", created)}',
        )

    new_offer_id = _extract_offer_id(created, 'eldorado')
    if not new_offer_id:
        return EditResult(ok=False, error='Legacy offer recreation created no new offer ID.')

    try:
        deleted = provider.delete_listing(client, listing.store_listing_id)
    except Exception as exc:
        deleted = SimpleNamespace(ok=False, error=str(exc))
    if not deleted or not getattr(deleted, 'ok', True):
        try:
            provider.delete_listing(client, new_offer_id)
        except Exception:
            logger.exception('Failed to clean up replacement Eldorado offer %s', new_offer_id)
        return EditResult(
            ok=False,
            error=(
                'Legacy offer recreation created the replacement but could not delete the old offer: '
                f'{getattr(deleted, "error", deleted)}'
            ),
        )

    response_data = created.data if hasattr(created, 'data') else created
    new_listing = _replace_in_db(
        listing,
        new_offer_id,
        response_data,
        payload,
        client=client,
        proxy_group=proxy_group,
    )
    _update_listing_db(new_listing, changes)
    return EditResult(ok=True, new_offer_id=new_offer_id)


# ── GameBoost ─────────────────────────────────────────────────────

def _gameboost_usd_to_eur_rate(listing: Listing) -> float:
    """USD→EUR rate for a GameBoost edit.

    Prefers a configured ``PostingDefault(game, 'gameboost').exchange_rate``;
    otherwise the shared default. Kept consistent with the create path.
    """
    from apps.posting.services.shared.pricing import DEFAULT_GAMEBOOST_USD_TO_EUR

    try:
        from apps.posting.models import PostingDefault
        pd = (
            PostingDefault.objects
            .filter(marketplace='gameboost', game=listing.game)
            .exclude(exchange_rate__isnull=True)
            .first()
        )
        if pd and pd.exchange_rate is not None:
            return float(pd.exchange_rate)
    except Exception:
        pass
    return DEFAULT_GAMEBOOST_USD_TO_EUR


def _edit_gameboost(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client('gameboost', store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group)

    payload = {}
    if 'title' in changes:
        payload['title'] = changes['title']
    if 'description' in changes:
        payload['description'] = changes['description']
    # The edit UI sends USD, but GameBoost lists in EUR (its API has no currency
    # field). Convert before posting AND before persisting so the marketplace
    # price and the stored Listing.price match the create path (EUR).
    db_changes = dict(changes)
    if 'price' in changes:
        eur_price = round(float(changes['price']) * _gameboost_usd_to_eur_rate(listing), 2)
        payload['price'] = eur_price
        db_changes['price'] = eur_price

    provider = get_provider('gameboost')
    result = provider.update_listing(client, listing.store_listing_id, payload)

    if not (result and getattr(result, 'ok', True)):
        error_msg = str(getattr(result, 'error', 'Unknown error'))
        _log(PostingLogLevel.ERROR,
             f'GameBoost edit failed for #{listing.pk}: {error_msg}',
             account=store,
             detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id})
        return EditResult(ok=False, error=error_msg)

    _update_listing_db(listing, db_changes)
    _log(PostingLogLevel.SUCCESS,
         f'Listing #{listing.pk} edited on GameBoost',
         account=store,
         detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id, 'changes': list(changes.keys())})
    return EditResult(ok=True)


# ── PlayerAuctions — single listing ──────────────────────────────

def _edit_pa_single(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    """Update one existing PA offer without cancelling or rebuilding it."""
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client('playerauctions', store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group)
    provider = get_provider('playerauctions')

    from core.marketplace.payload_extractor import extract_create_payload
    from apps.posting.services.pool.replenisher import _apply_pa_auto_delivery_credentials

    original_payload = extract_create_payload(
        listing.raw_data or {}, 'playerauctions', client=client, proxy_group=proxy_group,
    )
    if not original_payload:
        return EditResult(ok=False, error='No original payload found - listing has no raw_data')

    linked_product = listing.listing_owned_products.select_related('owned_product').first()
    if not linked_product:
        return EditResult(ok=False, error='No linked credential found - cannot update PA listing')

    pool_offer = PoolOffer.objects.filter(listing=listing).select_related('pool').first()
    active_offers = list(OfferPoolActiveOffer.objects.filter(listing=listing).select_related('pool'))
    active_offer = active_offers[0] if active_offers else None
    legacy_pool = OfferPool.objects.filter(listing=listing).first()
    effective_pool = pool_offer.pool if pool_offer else (
        active_offer.pool if active_offer else legacy_pool
    )
    if 'title' in changes and active_offer:
        try:
            tracking_code = extract_tracking_code(
                listing.title,
                original_payload.get('title', ''),
                getattr(linked_product.owned_product, 'ref_key', ''),
            )
            if not tracking_code:
                return EditResult(
                    ok=False,
                    error='PlayerAuctions title edit is blocked because the existing unique code could not be verified.',
                )
            changes = dict(changes)
            changes['title'] = append_tracking_code_for_code(
                changes['title'],
                tracking_code,
            )
        except ValueError as exc:
            return EditResult(ok=False, error=f'PlayerAuctions title code error: {exc}')
    _apply_pa_changes(original_payload, changes)
    _apply_pa_auto_delivery_credentials(original_payload, linked_product.owned_product, pool=effective_pool)

    result = provider.update_listing(
        client,
        listing.store_listing_id,
        {'payload': original_payload, 'proxy_group': proxy_group},
    )
    if not (result and getattr(result, 'ok', False)):
        error_message = str(getattr(result, 'error', 'PlayerAuctions edit failed'))
        _log(
            PostingLogLevel.ERROR,
            f'PA same-offer edit failed for #{listing.pk}: {error_message}',
            account=store,
            detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id},
        )
        return EditResult(ok=False, error=error_message)

    response_data = getattr(result, 'data', {}) or {}
    replacement_offer_id = str(response_data.get('replacementOfferId') or '').strip()
    old_offer_id = listing.store_listing_id
    extra_fields = []
    if replacement_offer_id and replacement_offer_id != old_offer_id:
        from apps.posting.services.relist import (
            _handoff_active_offer_replacement,
            _playerauctions_expiry_after_relist,
        )

        renewed_at = timezone.now()
        listing.store_listing_id = replacement_offer_id
        listing.listed_at = renewed_at
        listing.marketplace_expires_at = _playerauctions_expiry_after_relist(
            original_payload, response_data, renewed_at,
        )
        extra_fields = ['store_listing_id', 'listed_at', 'marketplace_expires_at']
        _handoff_active_offer_replacement(active_offers, replacement_offer_id)

    _update_listing_db(listing, changes, extra_fields=extra_fields)
    _log(
        PostingLogLevel.SUCCESS,
        f'PA same-offer edit succeeded for #{listing.pk}',
        account=store,
        detail={
            'listing_id': listing.pk,
            'offer_id': old_offer_id,
            'replacement_offer_id': replacement_offer_id or None,
            'changes': list(changes.keys()),
        },
    )
    return EditResult(ok=True, new_offer_id=replacement_offer_id or None)


def _edit_pa_single_cancel_recreate(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    """Legacy cancellation/recreate flow retained only for explicit future recovery tooling."""
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client('playerauctions', store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group)
    provider = get_provider('playerauctions')

    from core.marketplace.payload_extractor import extract_create_payload
    from apps.posting.services.pool.replenisher import _apply_pa_auto_delivery_credentials

    raw = listing.raw_data or {}
    original_payload = extract_create_payload(raw, 'playerauctions', client=client, proxy_group=proxy_group)
    if not original_payload:
        _log(
            PostingLogLevel.ERROR,
            f'PA edit: no original payload for #{listing.pk}',
            account=store,
        )
        return EditResult(ok=False, error='No original payload found - listing has no raw_data')

    lop = listing.listing_owned_products.select_related('owned_product').first()
    if not lop:
        _log(
            PostingLogLevel.ERROR,
            f'PA edit: no linked credential for #{listing.pk}',
            account=store,
            detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id},
        )
        return EditResult(ok=False, error='No linked credential found - cannot rebuild PA listing')

    _apply_pa_changes(original_payload, changes)
    pool_offer = PoolOffer.objects.filter(listing=listing).select_related('pool').first()
    active_offers = list(
        OfferPoolActiveOffer.objects.filter(listing=listing)
        .select_related('pool', 'pool_offer__pool')
    )
    active_offer = active_offers[0] if active_offers else None
    legacy_pool = OfferPool.objects.filter(listing=listing).first()
    effective_pool = (
        pool_offer.pool
        if pool_offer
        else (
            active_offer.pool_offer.pool
            if active_offer and active_offer.pool_offer_id
            else (active_offer.pool if active_offer else legacy_pool)
        )
    )
    _apply_pa_auto_delivery_credentials(original_payload, lop.owned_product, pool=effective_pool)

    # Step 1: Cancel a live offer only.  A closed/deleted clone is already
    # absent from PA, so recreating it must not issue a second delete request.
    if listing.status not in (ListingStatus.CLOSED, ListingStatus.DELETED):
        try:
            cancel_result = provider.delete_listing(client, listing.store_listing_id)
            if cancel_result and hasattr(cancel_result, 'ok') and not cancel_result.ok:
                error_msg = str(getattr(cancel_result, 'error', 'Cancel failed'))
                _log(PostingLogLevel.ERROR,
                     f'PA cancel failed for #{listing.pk}: {error_msg}',
                     account=store,
                     detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id})
                return EditResult(ok=False, error=f'Cancel failed: {error_msg}')
        except Exception as exc:
            _log(PostingLogLevel.ERROR,
                 f'PA cancel failed for #{listing.pk}: {exc}',
                 account=store)
            return EditResult(ok=False, error=f'Cancel failed: {exc}')

    old_offer_id = listing.store_listing_id

    def _mark_listing_orphaned(error_message: str) -> None:
        listing.status = ListingStatus.DELETED
        listing.removed_at = timezone.now()
        listing.raw_data = {
            **(listing.raw_data or {}),
            'edit_recreate_failed': error_message,
        }
        listing.save(update_fields=['status', 'removed_at', 'raw_data', 'updated_at'])
        for current_active_offer in active_offers:
            current_active_offer.status = OfferPoolActiveOfferStatus.FAILED
            current_active_offer.save(update_fields=['status', 'updated_at'])

    # Step 4: Create new offer
    try:
        create_result = provider.create_listing(client, {
            'payload': original_payload,
            'proxy_group': proxy_group,
        })
    except Exception as exc:
        _log(PostingLogLevel.ERROR,
             f'PA recreate failed for #{listing.pk}: {exc}',
             account=store,
             detail={'listing_id': listing.pk, 'old_offer_id': listing.store_listing_id})
        _mark_listing_orphaned(str(exc))
        return EditResult(ok=False, error=f'Recreate failed (offer was cancelled): {exc}')

    if not (create_result and getattr(create_result, 'ok', True)):
        error_msg = str(getattr(create_result, 'error', 'Create failed'))
        _log(PostingLogLevel.ERROR,
             f'PA recreate failed for #{listing.pk}: {error_msg}',
             account=store,
             detail={'listing_id': listing.pk, 'old_offer_id': listing.store_listing_id})
        _mark_listing_orphaned(error_msg)
        return EditResult(ok=False, error=f'Recreate failed (offer was cancelled): {error_msg}')

    from apps.posting.services.shared.utils import extract_listing_id
    new_offer_id = extract_listing_id(create_result.data)
    if not new_offer_id:
        _log(PostingLogLevel.WARNING,
             f'PA recreate: no offer ID in response for #{listing.pk}',
             account=store)
        _mark_listing_orphaned('Recreate succeeded but no offer ID returned')
        return EditResult(ok=False, error='Recreate succeeded but no offer ID returned')

    # Step 5: Atomically retain the same local account/clone ownership while
    # recording PA's replacement offer ID and its fresh lifecycle window.
    from apps.posting.services.relist import (
        _handoff_active_offer_replacement,
        _playerauctions_expiry_after_relist,
    )

    renewed_at = timezone.now()
    marketplace_expires_at = _playerauctions_expiry_after_relist(
        original_payload,
        getattr(create_result, 'data', None),
        renewed_at,
    )
    old_offer_id = listing.store_listing_id
    listing.store_listing_id = new_offer_id
    listing.status = ListingStatus.LISTED
    listing.removed_at = None
    listing.listed_at = renewed_at
    listing.marketplace_expires_at = marketplace_expires_at
    _update_listing_db(
        listing,
        changes,
        extra_fields=[
            'store_listing_id', 'status', 'removed_at', 'listed_at',
            'marketplace_expires_at',
        ],
    )

    # Rebind every matching clone and its exact pool item before the response
    # is returned. A PA edit cancels/recreates the remote offer, so retaining
    # an old ID here would make the card and future sale reconciliation stale.
    if not active_offers:
        active_offers = list(OfferPoolActiveOffer.objects.filter(
            pool_offer__listing__integration_account=store,
            store_listing_id=old_offer_id,
        ).select_related('pool_item'))
    _handoff_active_offer_replacement(active_offers, new_offer_id)

    _log(PostingLogLevel.SUCCESS,
         f'PA listing #{listing.pk} edited: {old_offer_id} → {new_offer_id}',
         account=store,
         detail={'listing_id': listing.pk, 'old_offer_id': old_offer_id,
                 'new_offer_id': new_offer_id, 'changes': list(changes.keys())})
    return EditResult(ok=True, new_offer_id=new_offer_id)


# ── PlayerAuctions — pool bulk edit ──────────────────────────────

def _edit_pa_pool_bulk(pool: OfferPool, changes: dict[str, Any]) -> BulkEditResult:
    """Edit active PA clone offers without leaving stale local listings."""
    from apps.posting.services.pool.replenisher import _apply_pa_auto_delivery_credentials
    from core.marketplace.payload_extractor import extract_create_payload

    store = pool.store
    result = BulkEditResult()

    active_offers = list(
        pool.active_offers
        .filter(status=OfferPoolActiveOfferStatus.ACTIVE)
        .select_related('pool_item', 'pool_item__owned_product', 'listing')
    )

    if not active_offers:
        return result

    result.total = len(active_offers)

    proxy_pool_inst = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        'playerauctions',
        store.credential,
        proxy_pool=proxy_pool_inst,
        proxy_group=proxy_group,
    )

    raw = pool.listing.raw_data or {}
    original_payload = extract_create_payload(raw, 'playerauctions', client=client, proxy_group=proxy_group)
    if not original_payload:
        # Older PA clones persisted only an offer ID.  Do not depend on a
        # remote detail read before editing them: the linked owned product is
        # sufficient to rebuild a safe replacement with fresh credentials.
        return _rebuild_pa_pool_edit_from_stock(
            pool, changes, active_offers, client, store, result,
        )

    _apply_pa_changes(original_payload, changes)

    relay_payloads: list[dict[str, Any]] = []
    ao_mapping: list[OfferPoolActiveOffer] = []
    invalid_offer_ids: list[str] = []

    for ao in active_offers:
        if not ao.pool_item or not ao.pool_item.owned_product:
            invalid_offer_ids.append(str(ao.store_listing_id))
            continue

        row_payload = copy.deepcopy(original_payload)
        _apply_pa_auto_delivery_credentials(row_payload, ao.pool_item.owned_product, pool=pool)
        tracking_code = pool_clone_tracking_code(
            pool.aggregate,
            ao.pool_item,
            uuid.uuid4().hex,
        )
        row_payload['title'] = append_tracking_code_for_code(
            row_payload.get('title', '') or pool.listing.title,
            tracking_code,
        )
        relay_payloads.append(row_payload)
        ao_mapping.append(ao)

    if invalid_offer_ids:
        _log(
            PostingLogLevel.ERROR,
            f'Pool #{pool.pk}: aborting edit because active offers lack credentials',
            account=store,
            detail={'pool_id': pool.pk, 'offer_ids': invalid_offer_ids},
        )
        result.failed = result.total
        result.errors.append(
            'Active offer(s) missing linked credential: ' + ', '.join(invalid_offer_ids)
        )
        return result

    if not relay_payloads:
        _log(
            PostingLogLevel.WARNING,
            f'Pool #{pool.pk}: no valid rows to upload before edit',
            account=store,
            detail={'pool_id': pool.pk},
        )
        result.failed = result.total
        result.errors.append('No valid credential rows to upload')
        return result

    relay_session = _resolve_pa_relay_session(store)
    if relay_session is None:
        result.failed = result.total
        result.errors.append(
            'PlayerAuctions relay session is unavailable; no active offer was cancelled.'
        )
        return result

    try:
        offer_ids = [int(ao.store_listing_id) for ao in ao_mapping]
    except (TypeError, ValueError) as exc:
        _log(
            PostingLogLevel.ERROR,
            f'Pool #{pool.pk}: invalid PA offer ID before cancel - {exc}',
            account=store,
            detail={'pool_id': pool.pk},
        )
        result.failed = result.total
        result.errors.append(f'Invalid PlayerAuctions offer ID: {exc}')
        return result

    edit_lock_state = _begin_pa_pool_edit_lock(pool)

    try:
        from apis_sdk.clients.marketplaces.playerauctions.models import PlayerAuctionsCancelRequest

        cancel_result = client.cancel_offers(PlayerAuctionsCancelRequest(offerIds=offer_ids))
        if cancel_result and hasattr(cancel_result, 'ok') and not cancel_result.ok:
            error_msg = str(getattr(cancel_result, 'error', 'Cancel failed'))
            _log(
                PostingLogLevel.ERROR,
                f'Pool #{pool.pk}: bulk cancel failed - {error_msg}',
                account=store,
                detail={'pool_id': pool.pk, 'offer_count': len(offer_ids)},
            )
            result.failed = result.total
            result.errors.append(f'Bulk cancel failed: {error_msg}')
            _finish_pa_pool_edit_lock(pool, edit_lock_state)
            return result
    except Exception as exc:
        _log(
            PostingLogLevel.ERROR,
            f'Pool #{pool.pk}: bulk cancel exception - {exc}',
            account=store,
            detail={'pool_id': pool.pk},
        )
        result.failed = result.total
        result.errors.append(f'Bulk cancel failed: {exc}')
        _finish_pa_pool_edit_lock(pool, edit_lock_state)
        return result

    _log(
        PostingLogLevel.INFO,
        f'Pool #{pool.pk}: cancelled {len(offer_ids)} offers for edit',
        account=store,
        detail={'pool_id': pool.pk, 'cancelled_ids': [str(i) for i in offer_ids]},
    )

    old_listing_ids = _mark_old_active_offer_listings_deleted(ao_mapping, pool)

    try:
        batch_result = _post_pa_relay_payloads(
            store,
            relay_payloads,
            session=relay_session,
        )
    except Exception as exc:
        with transaction.atomic():
            for ao in ao_mapping:
                _return_ao_to_pending(ao, f'Edit recreate failed after cancel: {str(exc)[:200]}')
        _log(
            PostingLogLevel.ERROR,
            f'Pool #{pool.pk}: bulk upload exception after cancel - {exc}',
            account=store,
            detail={'pool_id': pool.pk, 'deactivated_listing_ids': old_listing_ids},
        )
        result.failed = result.total
        result.errors.append(f'Bulk upload failed after cancel: {exc}')
        _finish_pa_pool_edit_lock(
            pool,
            edit_lock_state,
            f'Manual PA edit failed after cancellation: {str(exc)[:200]}',
        )
        return result

    with transaction.atomic():
        for idx, ao in enumerate(ao_mapping):
            if idx in batch_result.successful:
                new_offer_id = batch_result.successful[idx]
                if not new_offer_id:
                    _return_ao_to_pending(ao, 'Edit recreate: no offer ID returned by PA')
                    result.failed += 1
                    result.errors.append(f'{_ao_login(ao)}: no offer ID in PA response')
                    continue

                renewed_at = timezone.now()
                from apps.posting.services.relist import _playerauctions_expiry_after_relist

                new_listing = Listing.objects.create(
                    is_instant=True,
                    integration_account=store,
                    game=pool.game,
                    store_listing_id=new_offer_id,
                    product_category=pool.listing.product_category,
                    variant=pool.listing.variant,
                    status=ListingStatus.LISTED,
                    title=relay_payloads[idx].get('title', changes.get('title', pool.listing.title)),
                    price=relay_payloads[idx].get('price', changes.get('price', pool.listing.price)),
                    currency=pool.listing.currency,
                    listed_at=renewed_at,
                    marketplace_expires_at=_playerauctions_expiry_after_relist(
                        original_payload,
                        None,
                        renewed_at,
                    ),
                    raw_data=normalize_offer_response(
                        'playerauctions',
                        {'offer_id': new_offer_id},
                        payload=relay_payloads[idx],
                    ),
                )

                if ao.pool_item and ao.pool_item.owned_product:
                    ListingOwnedProduct.objects.create(
                        listing=new_listing,
                        owned_product=ao.pool_item.owned_product,
                    )

                ao.store_listing_id = new_offer_id
                ao.listing = new_listing
                ao.status = OfferPoolActiveOfferStatus.ACTIVE
                ao.save(update_fields=[
                    'store_listing_id', 'listing', 'status', 'updated_at',
                ])

                if ao.pool_item:
                    ao.pool_item.target_offer_id = new_offer_id
                    ao.pool_item.save(update_fields=['target_offer_id', 'updated_at'])

                result.succeeded += 1
            elif idx in batch_result.failed:
                error_msg = batch_result.failed[idx]
                _return_ao_to_pending(ao, f'Edit recreate failed: {error_msg[:200]}')
                result.failed += 1
                result.errors.append(f'{_ao_login(ao)}: {error_msg}')
            else:
                _return_ao_to_pending(ao, 'Edit recreate failed: no PA result returned')
                result.failed += 1
                result.errors.append(f'{_ao_login(ao)}: no PA result returned')

    _update_listing_db(pool.listing, changes)
    if result.failed:
        _finish_pa_pool_edit_lock(
            pool,
            edit_lock_state,
            'Manual PA edit recreated only some offers or failed after cancellation. '
            'Review and use the explicit per-account relist action; automatic replenishment is paused.',
        )
    else:
        _finish_pa_pool_edit_lock(pool, edit_lock_state)

    _log(
        PostingLogLevel.SUCCESS if result.failed == 0 else PostingLogLevel.WARNING,
        f'Pool #{pool.pk} edit: {result.succeeded}/{result.total} recreated'
        + (f', {result.failed} returned to pending' if result.failed else ''),
        account=store,
        detail={
            'pool_id': pool.pk,
            'total': result.total,
            'succeeded': result.succeeded,
            'failed': result.failed,
            'changes': list(changes.keys()),
            'deactivated_listing_ids': old_listing_ids,
        },
    )
    return result


def _rebuild_pa_pool_edit_from_stock(
    pool: OfferPool,
    changes: dict[str, Any],
    active_offers: list[OfferPoolActiveOffer],
    client: Any,
    store: IntegrationAccount,
    result: BulkEditResult,
) -> BulkEditResult:
    """Recreate legacy PA clones from locally linked owned-stock data.

    Historical PA clone records may retain only a remote ID.  A title or
    description edit must not depend on a remote-detail read in that case.  The
    linked owned product supplies a safe source payload and fresh credentials;
    remote offers are cancelled only after that local source has been checked.
    """
    invalid_ids = [
        str(active_offer.store_listing_id)
        for active_offer in active_offers
        if not active_offer.pool_item
        or not active_offer.pool_item.owned_product
        or not isinstance(active_offer.pool_item.owned_product.raw_data, dict)
        or not active_offer.pool_item.owned_product.raw_data
    ]
    if invalid_ids:
        result.failed = result.total
        result.errors.append(
            'Cannot rebuild active offer(s) without owned-stock source data: '
            + ', '.join(invalid_ids)
        )
        return result

    try:
        offer_ids = [int(active_offer.store_listing_id) for active_offer in active_offers]
        from apis_sdk.clients.marketplaces.playerauctions.models import PlayerAuctionsCancelRequest
        cancel_result = client.cancel_offers(PlayerAuctionsCancelRequest(offerIds=offer_ids))
        if cancel_result and hasattr(cancel_result, 'ok') and not cancel_result.ok:
            error_msg = str(getattr(cancel_result, 'error', 'Cancel failed'))
            result.failed = result.total
            result.errors.append(f'PlayerAuctions cancel failed: {error_msg}')
            return result
    except Exception as exc:
        result.failed = result.total
        result.errors.append(f'PlayerAuctions cancel failed: {exc}')
        return result

    old_listing_ids = _mark_old_active_offer_listings_deleted(active_offers, pool)
    _update_listing_db(pool.listing, changes)
    queued_items: list[OfferPoolItem] = []
    with transaction.atomic():
        for active_offer in active_offers:
            _return_ao_to_pending(
                active_offer,
                'Rebuilding PlayerAuctions clone after marketplace edit',
            )
            if active_offer.pool_item_id:
                queued_items.append(
                    _claim_exact_item_for_pa_edit(active_offer.pool_item, pool.pool_offer)
                )
        pool.pool_offer.current_remote_count = 0
        pool.pool_offer.save(update_fields=['current_remote_count', 'updated_at'])

    from apps.posting.services.pool.allocation import mark_item_failed
    from apps.posting.services.pool.replenisher import _rebuild_pa_offer_from_stock
    pushed = 0
    for item in queued_items:
        try:
            pushed += _rebuild_pa_offer_from_stock(pool, client, item, proxy_group)
        except Exception as exc:
            logger.exception('Pool #%s: exact PA source rebuild failed for item %s', pool.pk, item.pk)
            mark_item_failed(
                item,
                error_message=f'PlayerAuctions source rebuild failed: {exc}',
                failure_stage='remote_push',
                remote_state='unknown',
            )
            result.errors.append(f'PlayerAuctions source rebuild failed for item {item.pk}: {exc}')

    pool.pool_offer.current_remote_count = pushed
    pool.pool_offer.save(update_fields=['current_remote_count', 'updated_at'])
    result.succeeded = pushed
    result.failed = result.total - result.succeeded
    if result.failed and not result.errors:
        failed_items = OfferPoolItem.objects.filter(
            pk__in=[active_offer.pool_item_id for active_offer in active_offers if active_offer.pool_item_id],
        ).exclude(status=OfferPoolItemStatus.PUSHED)
        errors = [item.error_message for item in failed_items if item.error_message]
        result.errors.append(
            'PlayerAuctions source rebuild did not create every replacement'
            + (': ' + '; '.join(errors[:3]) if errors else '')
        )

    _log(
        PostingLogLevel.SUCCESS if result.failed == 0 else PostingLogLevel.WARNING,
        f'Pool #{pool.pk}: rebuilt {result.succeeded}/{result.total} legacy PA clone(s) after edit',
        account=store,
        detail={
            'pool_id': pool.pk,
            'succeeded': result.succeeded,
            'failed': result.failed,
            'deactivated_listing_ids': old_listing_ids,
            'changes': list(changes.keys()),
        },
    )
    return result


def _claim_exact_item_for_pa_edit(item: OfferPoolItem, pool_offer: PoolOffer) -> OfferPoolItem:
    """Reserve one known-safe pool item for a replacement edit and give it a new code."""
    token = uuid.uuid4()
    now = timezone.now()
    item.pool_offer = pool_offer
    item.status = OfferPoolItemStatus.QUEUED
    item.claim_token = token
    item.claimed_at = now
    item.failure_stage = ''
    item.remote_state = ''
    item.error_message = ''
    item.save(update_fields=[
        'pool_offer', 'status', 'claim_token', 'claimed_at', 'failure_stage',
        'remote_state', 'error_message', 'updated_at',
    ])
    PoolDispatchAttempt.objects.create(
        idempotency_key=token,
        item=item,
        pool_offer=pool_offer,
        operation=PoolDispatchOperation.PUSH,
        status=PoolDispatchStatus.IN_PROGRESS,
        request_fingerprint=f'pool-edit:{pool_offer.pk}:{item.pk}:{token}',
        started_at=now,
    )
    return item


# ── Helpers ───────────────────────────────────────────────────────

def _update_listing_db(listing: Listing, changes: dict[str, Any], extra_fields: list[str] | None = None) -> None:
    """Update Listing model fields + raw_data from changes dict."""
    update_fields = list(extra_fields or [])

    if 'title' in changes:
        listing.title = changes['title']
        update_fields.append('title')
    if 'price' in changes:
        listing.price = changes['price']
        update_fields.append('price')

    # Merge changes into raw_data.  PlayerAuctions target increases rebuild from
    # the nested create payload, so the visible staff edit must update that
    # authoritative template as well as the flat display fields.
    raw = _raw_data_with_changes(listing.raw_data, changes)
    listing.raw_data = raw
    if 'raw_data' not in update_fields:
        update_fields.append('raw_data')

    update_fields.append('updated_at')
    listing.save(update_fields=update_fields)


def _apply_pa_changes(payload: dict, changes: dict[str, Any]) -> None:
    """Apply title/description/price changes to a PA create payload.

    Key names match PlayerAuctionsMapper.build_from_raw output:
    title, offerDesc, price.
    """
    if 'title' in changes:
        payload[_PA_TITLE] = changes['title']
    if 'description' in changes:
        payload[_PA_DESC] = changes['description']
    if 'price' in changes:
        payload[_PA_PRICE] = round(float(changes['price']), 2)


def _pa_payload_to_excel_row(payload: dict) -> dict[str, Any]:
    """Convert a PA API payload dict to an Excel row dict for bulk upload."""
    from apps.posting.pipeline.playerauctions.common import _fake_personal_info

    auto = payload.get('autoDelivery', {})
    personal = _fake_personal_info()

    return {
        'Game': payload.get('gameTitle', payload.get('game', '')),
        'Server': payload.get('server', payload.get('serverTitle', '')),
        'Faction': payload.get('faction', ''),
        'Listing Price': payload.get(_PA_PRICE, payload.get('listingPrice', payload.get('offerPrice', ''))),
        'Seller After-Sale Protection': payload.get('sellerAfterSaleProtection', 7),
        'Offer Duration': payload.get('offerDuration', 30),
        'Cover image (PA hosted)': '',
        'Title': payload.get(_PA_TITLE, ''),
        'Description': payload.get(_PA_DESC, payload.get('description', '')),
        'Delivery Method': 'Automatic',
        'Login name  (Auto)': auto.get('loginName', ''),
        'Password': auto.get('password', ''),
        'Character name': auto.get('characterName', personal.get('first_name', '')),
        'Registration CD Key': '',
        'Parental password': auto.get('parentalPassword', ''),
        'Security question': '',
        'Security question answer': '',
        'First name': personal['first_name'],
        'Last name': personal['last_name'],
        'Phone with area code': personal['phone'],
        'Email': auto.get('ownerEmail', payload.get('email', '')),
        'City': personal['city'],
        'Country': personal['country'],
        'Birth Date': personal['birth_date'],
        'Extra information': auto.get('instruction', ''),
        'Login name': '',
        'Delivery guarantee': '',
        'Delivery info': '',
    }


def _post_pa_relay_payloads(
    store: IntegrationAccount,
    payloads: list[dict[str, Any]],
    *,
    session: tuple[str, str, str, str, str] | None = None,
):
    """Submit PA JSON payloads through the working relay JSON branch.

    PlayerAuctions clone payloads contain numeric ``gameId`` and ``serverId``.
    Passing them through the Excel uploader turns the numeric game ID into the
    name-based ``Game`` cell and causes PA to reject otherwise valid GTA rows.
    ``PARelayPoster`` preserves those provider IDs when a payload has
    ``serverId`` and returns the same index-based result contract used below.
    """
    resolved_session = session or _resolve_pa_relay_session(store)
    if resolved_session is None:
        from apps.posting.services.stock.pa_bulk_uploader import PABatchResult

        return PABatchResult(
            failed={
                idx: 'PA relay: could not obtain an access token for offer edit'
                for idx in range(len(payloads))
            }
        )
    token, cookie, store_slug, relay_url, relay_secret = resolved_session
    poster = PARelayPoster(
        relay_url=relay_url,
        relay_secret=relay_secret,
    )
    result = poster.post_batch(
        token,
        store_slug,
        payloads,
        cookie=(cookie or token),
    )

    # This custom JSON relay route bypasses the PA SDK facade's normal
    # authentication retry.  A cached credential can be accepted for the
    # cancellation but rejected for the subsequent recreate.  On *only* a
    # 401/Unauthorized result, obtain one forced-fresh relay session and retry
    # only the rejected rows.  Successful rows are never reposted.
    retry_indices = [
        idx
        for idx, error in result.failed.items()
        if _is_pa_unauthorized(error)
    ]
    if not retry_indices:
        return result

    refreshed_session = _resolve_pa_relay_session(store, force_refresh=True)
    if refreshed_session is None:
        return result
    fresh_token, fresh_cookie, fresh_store_slug, fresh_relay_url, fresh_relay_secret = refreshed_session
    retry_result = PARelayPoster(
        relay_url=fresh_relay_url,
        relay_secret=fresh_relay_secret,
    ).post_batch(
        fresh_token,
        fresh_store_slug,
        [payloads[idx] for idx in retry_indices],
        cookie=(fresh_cookie or fresh_token),
    )
    for retry_idx, original_idx in enumerate(retry_indices):
        if retry_idx in retry_result.successful:
            result.successful[original_idx] = retry_result.successful[retry_idx]
            result.failed.pop(original_idx, None)
        elif retry_idx in retry_result.failed:
            result.failed[original_idx] = retry_result.failed[retry_idx]
    return result


def _is_pa_unauthorized(error: Any) -> bool:
    """Recognize only PA authentication rejections eligible for one retry."""
    value = str(error or '').lower()
    return 'unauthorized' in value or 'http 401' in value or 'status=401' in value


def _resolve_pa_relay_session(
    store: IntegrationAccount,
    *,
    force_refresh: bool = False,
) -> tuple[str, str, str, str, str] | None:
    """Return a usable PA relay session before an offer-cancel operation."""
    credentials = getattr(getattr(store, 'credential', None), 'credentials', None) or {}
    username = credentials.get('username', '')
    password = credentials.get('password', '')
    store_slug = credentials.get('store_slug', '')
    relay_url = credentials.get('relay_url', 'http://35.196.132.30:3001')
    relay_secret = credentials.get('relay_secret', 'pa-relay-secret-2026')
    token = credentials.get('access_token', '')
    cookie = credentials.get('cookie', '')
    if username and password and store_slug and (force_refresh or not token):
        token, cookie = fetch_relay_token(
            username,
            password,
            store_slug,
            relay_url=relay_url,
            relay_secret=relay_secret,
            force_refresh=force_refresh,
        )
    if not token:
        return None
    return token, cookie, store_slug, relay_url, relay_secret


def _begin_pa_pool_edit_lock(pool: OfferPool) -> tuple[str, str] | None:
    """Pause only this PA lane before its active offers are cancelled for edit."""
    pool_offer = getattr(pool, 'pool_offer', None)
    if pool_offer is None:
        return None
    previous = (pool_offer.status, pool_offer.last_error)
    pool_offer.status = PoolOfferStatus.ERROR
    pool_offer.last_error = (
        'Manual PlayerAuctions offer edit is recreating its selected accounts. '
        'Automatic replenishment is temporarily paused.'
    )
    pool_offer.save(update_fields=['status', 'last_error', 'updated_at'])
    return previous


def _finish_pa_pool_edit_lock(
    pool: OfferPool,
    previous: tuple[str, str] | None,
    error: str = '',
) -> None:
    """Restore a clean edit lane or retain an explicit pause after cancellation."""
    if previous is None:
        return
    pool_offer = getattr(pool, 'pool_offer', None)
    if pool_offer is None:
        return
    if error:
        pool_offer.status = PoolOfferStatus.ERROR
        pool_offer.last_error = error
    else:
        pool_offer.status, pool_offer.last_error = previous
    pool_offer.save(update_fields=['status', 'last_error', 'updated_at'])


def _mark_old_active_offer_listings_deleted(
    active_offers: list[OfferPoolActiveOffer],
    pool: OfferPool,
) -> list[int]:
    """Mark clone listings deleted after their remote PA offers are cancelled."""
    old_listing_ids: list[int] = []
    with transaction.atomic():
        for ao in active_offers:
            old_listing = ao.listing
            if not old_listing or old_listing.pk == pool.listing_id:
                continue
            old_listing.status = ListingStatus.DELETED
            old_listing.removed_at = timezone.now()
            old_listing.save(update_fields=['status', 'removed_at', 'updated_at'])
            ListingOwnedProduct.objects.filter(listing=old_listing).delete()
            old_listing_ids.append(old_listing.pk)
    return old_listing_ids


def _return_ao_to_pending(ao: OfferPoolActiveOffer, error_message: str) -> None:
    """Mark an active offer failed and return its credential to the pool."""
    ao.status = OfferPoolActiveOfferStatus.FAILED
    ao.save(update_fields=['status', 'updated_at'])
    if ao.pool_item:
        ao.pool_item.status = OfferPoolItemStatus.PENDING
        ao.pool_item.pool_offer = None
        ao.pool_item.error_message = error_message
        ao.pool_item.target_offer_id = ''
        ao.pool_item.remote_credential_id = ''
        ao.pool_item.remote_state = 'absent'
        ao.pool_item.pushed_at = None
        ao.pool_item.save(update_fields=[
            'status', 'pool_offer', 'error_message', 'target_offer_id',
            'remote_credential_id', 'remote_state', 'pushed_at', 'updated_at',
        ])


def _ao_login(ao: OfferPoolActiveOffer) -> str:
    if ao.pool_item and ao.pool_item.owned_product:
        return ao.pool_item.owned_product.login
    return '?'


def _raw_data_with_changes(raw_data: dict | None, changes: dict[str, Any]) -> dict:
    """Persist display edits and keep a PA create template in sync."""
    raw = dict(raw_data or {})
    for key in ('title', 'description', 'price'):
        if key in changes:
            raw[key] = _json_safe_change_value(changes[key])

    payload = raw.get('payload')
    details = raw.get('details')
    is_pa_payload = isinstance(payload, dict) and (
        'autoDelivery' in payload or 'gameId' in payload
    )
    is_pa_details = isinstance(details, dict) and (
        'autoDelivery' in details or 'gameId' in details
    )

    if is_pa_payload:
        payload = dict(payload)
        if 'title' in changes:
            payload['title'] = changes['title']
        if 'description' in changes:
            payload['offerDesc'] = changes['description']
            payload['description'] = changes['description']
        if 'price' in changes:
            payload['price'] = _json_safe_change_value(changes['price'])
        raw['payload'] = payload

    if is_pa_details:
        details = dict(details)
        if 'title' in changes:
            details['title'] = changes['title']
        if 'description' in changes:
            details['offerDesc'] = changes['description']
            details['description'] = changes['description']
        if 'price' in changes:
            details['price'] = _json_safe_change_value(changes['price'])
        raw['details'] = details
    return raw


def _json_safe_change_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
