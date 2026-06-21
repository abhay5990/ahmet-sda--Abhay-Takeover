"""Offer editor — update title / description / price on marketplace.

Supports three strategies:
- Eldorado: PUT update_offer directly
- GameBoost: PATCH update_offer directly
- PlayerAuctions: cancel_offers + bulk_upload (single or pool-wide)
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
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
    PostingLog,
    PostingLogLevel,
)

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


def edit_pool_offers(pool: OfferPool, changes: dict[str, Any]) -> BulkEditResult:
    """Edit all offers in a pool.

    - Append strategy (Eldorado/GB): edit the single pool listing
    - Clone strategy (PA): cancel all active offers + bulk recreate
    """
    if pool.strategy == OfferPool.Strategy.CLONE:
        return _edit_pa_pool_bulk(pool, changes)
    else:
        result = edit_offer(pool.listing, changes)
        bulk = BulkEditResult(total=1)
        if result.ok:
            bulk.succeeded = 1
        else:
            bulk.failed = 1
            bulk.errors.append(result.error)
        return bulk


# ── Eldorado ──────────────────────────────────────────────────────

def _edit_eldorado(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    """Edit an Eldorado listing via PUT /api/flexibleOffers/account/{id}/details."""
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client('eldorado', store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group)

    offer_id = listing.store_listing_id
    raw = listing.raw_data or {}

    # Fetch live account details to include them in the update payload
    account_details: list[dict] = []
    creds_result = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
    if creds_result.ok and creds_result.data:
        resp = creds_result.data
        src = resp.accountsDetails or resp.secretDetails or []
        account_details = [
            {'id': e.id, 'secretDetails': e.secretDetails}
            for e in src if e.secretDetails
        ]
    if not account_details:
        # Fallback: use stored credential entries
        account_details = [
            {'id': e.get('id', ''), 'secretDetails': e['secretDetails']}
            for e in (raw.get('_credential_entries') or [])
            if e.get('secretDetails')
        ]

    # Build details block — apply changes on top of raw_data values
    raw_price = raw.get('pricePerUnit') or {}
    details: dict[str, Any] = {
        'pricing': {
            'quantity': len(account_details) or raw.get('quantity', 1),
            'pricePerUnit': {
                'amount': float(changes['price']) if 'price' in changes else float(raw_price.get('amount', 0)),
                'currency': raw_price.get('currency', 'USD'),
            },
            'volumeDiscounts': raw.get('volumeDiscounts') or None,
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
    trade_env_id = str(trade_envs[0]['id']) if trade_envs else '0'
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
        'accountDetails': account_details,
    }

    provider = get_provider('eldorado')
    result = provider.update_listing(client, offer_id, payload)

    if not (result and getattr(result, 'ok', True)):
        error_msg = str(getattr(result, 'error', 'Unknown error'))
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


# ── GameBoost ─────────────────────────────────────────────────────

def _edit_gameboost(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client('gameboost', store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group)

    payload = {}
    if 'title' in changes:
        payload['title'] = changes['title']
    if 'description' in changes:
        payload['description'] = changes['description']
    if 'price' in changes:
        payload['price'] = float(changes['price'])

    provider = get_provider('gameboost')
    result = provider.update_listing(client, listing.store_listing_id, payload)

    if not (result and getattr(result, 'ok', True)):
        error_msg = str(getattr(result, 'error', 'Unknown error'))
        _log(PostingLogLevel.ERROR,
             f'GameBoost edit failed for #{listing.pk}: {error_msg}',
             account=store,
             detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id})
        return EditResult(ok=False, error=error_msg)

    _update_listing_db(listing, changes)
    _log(PostingLogLevel.SUCCESS,
         f'Listing #{listing.pk} edited on GameBoost',
         account=store,
         detail={'listing_id': listing.pk, 'offer_id': listing.store_listing_id, 'changes': list(changes.keys())})
    return EditResult(ok=True)


# ── PlayerAuctions — single listing ──────────────────────────────

def _edit_pa_single(listing: Listing, changes: dict[str, Any], store: IntegrationAccount) -> EditResult:
    """Edit a single PA listing: validate, cancel, then recreate."""
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
    pool = OfferPool.objects.filter(listing=listing).first()
    active_offer = OfferPoolActiveOffer.objects.filter(listing=listing).select_related('pool').first()
    effective_pool = pool or (active_offer.pool if active_offer else None)
    _apply_pa_auto_delivery_credentials(original_payload, lop.owned_product, pool=effective_pool)

    # Step 1: Cancel existing offer
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
        if active_offer:
            active_offer.status = OfferPoolActiveOfferStatus.FAILED
            active_offer.save(update_fields=['status', 'updated_at'])

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

    # Step 5: Update DB
    old_offer_id = listing.store_listing_id
    listing.store_listing_id = new_offer_id
    _update_listing_db(listing, changes, extra_fields=['store_listing_id'])

    # Update OfferPoolActiveOffer if exists
    if active_offer:
        active_offer.store_listing_id = new_offer_id
        active_offer.save(update_fields=['store_listing_id', 'updated_at'])
    else:
        OfferPoolActiveOffer.objects.filter(
            pool__store=store,
            store_listing_id=old_offer_id,
        ).update(store_listing_id=new_offer_id)

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
    from apps.posting.services.stock.pa_bulk_uploader import PABulkUploader
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
        _log(
            PostingLogLevel.ERROR,
            f'Pool #{pool.pk}: no original payload - aborting before cancel',
            account=store,
            detail={'pool_id': pool.pk},
        )
        result.failed = result.total
        result.errors.append('No original payload - no remote changes made')
        return result

    _apply_pa_changes(original_payload, changes)

    excel_rows: list[dict[str, Any]] = []
    ao_mapping: list[OfferPoolActiveOffer] = []
    invalid_offer_ids: list[str] = []

    for ao in active_offers:
        if not ao.pool_item or not ao.pool_item.owned_product:
            invalid_offer_ids.append(str(ao.store_listing_id))
            continue

        row_payload = copy.deepcopy(original_payload)
        _apply_pa_auto_delivery_credentials(row_payload, ao.pool_item.owned_product, pool=pool)
        excel_rows.append(_pa_payload_to_excel_row(row_payload))
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

    if not excel_rows:
        _log(
            PostingLogLevel.WARNING,
            f'Pool #{pool.pk}: no valid rows to upload before edit',
            account=store,
            detail={'pool_id': pool.pk},
        )
        result.failed = result.total
        result.errors.append('No valid credential rows to upload')
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
        return result

    _log(
        PostingLogLevel.INFO,
        f'Pool #{pool.pk}: cancelled {len(offer_ids)} offers for edit',
        account=store,
        detail={'pool_id': pool.pk, 'cancelled_ids': [str(i) for i in offer_ids]},
    )

    old_listing_ids = _mark_old_active_offer_listings_deleted(ao_mapping, pool)

    try:
        from apis_sdk.factories.playerauctions_factory import PlayerAuctionsFactory
        from apis_sdk.factories.transport_factory import TransportFactory

        creds = store.credential.credentials
        transport = TransportFactory.create_requests_transport(timeout=60.0)
        facade = PlayerAuctionsFactory.create(
            username=creds.get('username', ''),
            password=creds.get('password', ''),
            access_token=creds.get('access_token', '') or creds.get('bearer_token', ''),
            transport=transport,
            proxy_pool=proxy_pool_inst,
            proxy_group=proxy_group,
        )

        uploader = PABulkUploader()
        batch_result = uploader.upload_batch(facade, excel_rows, proxy_group=proxy_group)
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

                new_listing = Listing.objects.create(
                    is_instant=True,
                    integration_account=store,
                    game=pool.game,
                    store_listing_id=new_offer_id,
                    product_category=pool.listing.product_category,
                    variant=pool.listing.variant,
                    title=changes.get('title', pool.listing.title),
                    price=changes.get('price', pool.listing.price),
                    currency=pool.listing.currency,
                    listed_at=timezone.now(),
                    raw_data=_raw_data_with_changes(pool.listing.raw_data, changes),
                )

                if ao.pool_item and ao.pool_item.owned_product:
                    ListingOwnedProduct.objects.create(
                        listing=new_listing,
                        owned_product=ao.pool_item.owned_product,
                    )

                ao.store_listing_id = new_offer_id
                ao.listing = new_listing
                ao.save(update_fields=['store_listing_id', 'listing', 'updated_at'])

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

    # Merge changes into raw_data
    if listing.raw_data is None:
        listing.raw_data = {}
    raw = dict(listing.raw_data)
    for key in ('title', 'description', 'price'):
        if key in changes:
            raw[key] = _json_safe_change_value(changes[key])
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
        ao.pool_item.error_message = error_message
        ao.pool_item.target_offer_id = ''
        ao.pool_item.pushed_at = None
        ao.pool_item.save(update_fields=[
            'status', 'error_message', 'target_offer_id', 'pushed_at', 'updated_at',
        ])


def _ao_login(ao: OfferPoolActiveOffer) -> str:
    if ao.pool_item and ao.pool_item.owned_product:
        return ao.pool_item.owned_product.login
    return '?'


def _raw_data_with_changes(raw_data: dict | None, changes: dict[str, Any]) -> dict:
    raw = dict(raw_data or {})
    for key in ('title', 'description', 'price'):
        if key in changes:
            raw[key] = _json_safe_change_value(changes[key])
    return raw


def _json_safe_change_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
