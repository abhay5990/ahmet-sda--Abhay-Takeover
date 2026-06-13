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
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    PostingLog,
    PostingLogLevel,
)

from apps.posting.services.shared.utils import extract_listing_id
from core.marketplace.normalizers import normalize_offer_response
from core.marketplace.payload_extractor import extract_create_payload

from .formatter import (
    build_credential_bundle,
    build_credential_render_context,
    format_credential_by_spec,
    format_credential_for_marketplace,
    render_template,
)

logger = logging.getLogger(__name__)

TASK_NAME = 'pool_replenish'


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


def replenish_pool(pool: OfferPool) -> int:
    """Push pending credentials from pool to the marketplace offer.

    Returns the number of credentials successfully pushed.
    """
    if pool.status != OfferPoolStatus.ACTIVE:
        return 0

    marketplace = pool.store.provider
    if marketplace == 'playerauctions':
        return _replenish_pa(pool)
    elif marketplace in ('eldorado', 'gameboost'):
        return _replenish_append(pool, marketplace)
    else:
        logger.warning('pool_replenish: unsupported marketplace %s for pool %d', marketplace, pool.pk)
        return 0


def _replenish_append(pool: OfferPool, marketplace: str) -> int:
    """Append credentials to existing offer (Eldorado / Gameboost)."""
    current_count = pool.current_remote_count or 0
    need = pool.target_count - current_count
    if need <= 0:
        return 0

    pending_items = list(
        pool.items.filter(status=OfferPoolItemStatus.PENDING)
        .select_related('owned_product')
        .order_by('order', 'created_at')[:need]
    )
    if not pending_items:
        _check_depleted(pool)
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

    offer_id = pool.listing.store_listing_id
    pushed = 0

    if marketplace == 'eldorado':
        pushed = _push_eldorado(pool, client, offer_id, pending_items, proxy_group)
    elif marketplace == 'gameboost':
        pushed = _push_gameboost(pool, client, offer_id, pending_items, proxy_group)

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
            item.status = OfferPoolItemStatus.FAILED
            item.error_message = str(exc)[:500]
            item.save(update_fields=['status', 'error_message', 'updated_at'])

    if not new_creds:
        return 0

    all_creds = existing_creds + new_creds

    # Try update_offer with appended credentials
    update_payload = {'accountSecretDetails': all_creds}
    result = client.update_offer(offer_id, update_payload, proxy_group=proxy_group)

    if result.ok:
        return _mark_items_pushed(valid_items, offer_id, listing=pool.listing)

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
    """Delete old offer and create new one with full credential set."""
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
        return 0

    # Delete old offer
    delete_result = client.delete_offer(old_offer_id, proxy_group=proxy_group)
    if not delete_result.ok:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: failed to delete old offer {old_offer_id}: {delete_result.error}",
            account=pool.store,
        )
        return 0

    return _create_eldorado_offer(pool, client, original_payload, all_creds, new_items, proxy_group)


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
            pool=pool,
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

    return _mark_items_pushed(new_items, new_offer_id, listing=pool.listing)


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
            item.status = OfferPoolItemStatus.FAILED
            item.error_message = str(exc)[:500]
            item.save(update_fields=['status', 'error_message', 'updated_at'])

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
            item.status = OfferPoolItemStatus.FAILED
            item.error_message = f"API error: {error_str[:200]}"
            item.save(update_fields=['status', 'error_message', 'updated_at'])
        return 0

    resp = result.data
    created = getattr(resp, 'created_count', len(valid_items))
    return _mark_items_pushed(valid_items[:created], offer_id, listing=pool.listing)


def _gameboost_recreate(
    pool: OfferPool,
    client: Any,
    old_offer_id: str,
    cred_strings: list[str],
    valid_items: list[OfferPoolItem],
    proxy_group: str | None,
) -> int:
    """Old format: delete offer → create new one with /account-offers/create.

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
        return 0

    # Extract existing credential from old offer before deleting
    existing_creds = _extract_existing_gameboost_credentials(original_payload)

    # Delete old offer
    delete_result = client.delete_offer(old_offer_id, proxy_group=proxy_group)
    if not delete_result.ok:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: failed to delete old Gameboost offer {old_offer_id}: {delete_result.error}",
            account=pool.store,
        )
        return 0

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
        return 0

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
    """PlayerAuctions: clone offers to maintain max_concurrent active offers."""
    active_count = pool.active_offers.filter(
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).count()

    need = pool.max_concurrent - active_count
    if need <= 0:
        return 0

    pending_items = list(
        pool.items.filter(status=OfferPoolItemStatus.PENDING)
        .select_related('owned_product')
        .order_by('order', 'created_at')[:need]
    )
    if not pending_items:
        _check_depleted(pool)
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

    # Get the original payload template from the pool's listing
    raw = pool.listing.raw_data or {}
    original_payload = extract_create_payload(
        raw,
        'playerauctions',
        client=client,
        proxy_group=proxy_group,
    )
    if not original_payload:
        _log(
            PostingLogLevel.ERROR,
            f"Pool #{pool.pk}: cannot clone PA offer — no original payload",
            account=store,
        )
        return 0

    pushed = 0
    for item in pending_items:
        try:
            pushed += _clone_pa_offer(pool, client, original_payload, item, proxy_group)
        except Exception as exc:
            logger.exception('pool_replenish: PA clone failed for item %d', item.pk)
            item.status = OfferPoolItemStatus.FAILED
            item.error_message = str(exc)[:500]
            item.save(update_fields=['status', 'error_message', 'updated_at'])

    pool.last_replenished_at = timezone.now()
    pool.save(update_fields=['last_replenished_at', 'updated_at'])

    _log(
        PostingLogLevel.SUCCESS if pushed > 0 else PostingLogLevel.WARNING,
        f"Pool #{pool.pk} PA replenish: {pushed}/{len(pending_items)} cloned",
        account=store,
        detail={'pool_id': pool.pk, 'pushed': pushed, 'attempted': len(pending_items)},
    )

    _check_depleted(pool)
    return pushed


def _clone_pa_offer(
    pool: OfferPool,
    client: Any,
    original_payload: dict,
    item: OfferPoolItem,
    proxy_group: str | None,
) -> int:
    """Create a single PA clone offer with new credentials."""
    payload = dict(original_payload)

    # Replace credentials with platform-aware format
    product = item.owned_product
    _apply_pa_auto_delivery_credentials(payload, product, pool=pool)

    result = client.create_offer(payload, proxy_group=proxy_group)
    if not result.ok:
        error_str = str(result.error) if result.error else 'Unknown error'
        item.status = OfferPoolItemStatus.FAILED
        item.error_message = f"PA create failed: {error_str[:200]}"
        item.save(update_fields=['status', 'error_message', 'updated_at'])
        return 0

    # Extract offer ID from response
    new_offer_id = extract_listing_id(result.data)
    if not new_offer_id:
        item.status = OfferPoolItemStatus.FAILED
        item.error_message = "PA create succeeded but no offer ID in response"
        item.save(update_fields=['status', 'error_message', 'updated_at'])
        return 0

    raw_data = normalize_offer_response(
        'playerauctions',
        result.data,
        payload=payload,
        client=client,
        proxy_group=proxy_group,
    )

    with transaction.atomic():
        # Create Listing for the clone
        new_listing = Listing.objects.create(
            is_instant=True,
            integration_account=pool.store,
            game=pool.game,
            store_listing_id=new_offer_id,
            variant=pool.listing.variant,
            title=pool.listing.title,
            price=pool.listing.price,
            currency=pool.listing.currency,
            raw_data=raw_data,
        )

        ListingOwnedProduct.objects.create(
            listing=new_listing,
            owned_product=product,
        )

        # Track active offer
        OfferPoolActiveOffer.objects.create(
            pool=pool,
            store_listing_id=new_offer_id,
            listing=new_listing,
            pool_item=item,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        )

        item.status = OfferPoolItemStatus.PUSHED
        item.pushed_at = timezone.now()
        item.target_offer_id = new_offer_id
        item.save(update_fields=['status', 'pushed_at', 'target_offer_id', 'updated_at'])

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
) -> int:
    """Compare PUSHED pool items against remote credentials and mark missing as CONSUMED.

    For each PUSHED item, re-format its credential string and check if it
    exists in the remote credential list. If not found → CONSUMED + unlink
    from listing.

    Returns the number of items marked as CONSUMED.
    """
    pushed_items = list(
        pool.items.filter(status=OfferPoolItemStatus.PUSHED)
        .select_related('owned_product')
    )
    if not pushed_items:
        return 0

    marketplace = pool.store.provider
    consumed = 0

    for item in pushed_items:
        try:
            expected_cred = format_credential_for_marketplace(
                item.owned_product, marketplace, pool=pool,
            )
        except Exception:
            continue

        if isinstance(expected_cred, dict):
            # PA dict format — not applicable here
            continue

        # Normalize whitespace for comparison
        expected_norm = expected_cred.strip()
        found = any(
            rc.strip() == expected_norm for rc in remote_creds
        )

        if not found:
            item.status = OfferPoolItemStatus.CONSUMED
            item.error_message = 'Removed from remote offer'
            item.save(update_fields=['status', 'error_message', 'updated_at'])

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


def _mark_items_pushed(items: list[OfferPoolItem], offer_id: str, listing: Listing | None = None) -> int:
    """Mark items as PUSHED, record target offer ID, and link OwnedProducts to Listing."""
    now = timezone.now()
    count = 0
    for item in items:
        if item.status == OfferPoolItemStatus.FAILED:
            continue
        item.status = OfferPoolItemStatus.PUSHED
        item.pushed_at = now
        item.target_offer_id = offer_id
        item.save(update_fields=['status', 'pushed_at', 'target_offer_id', 'updated_at'])

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

        count += 1
    return count


def _check_depleted(pool: OfferPool) -> None:
    """If no pending items remain, mark pool as DEPLETED."""
    remaining = pool.items.filter(status=OfferPoolItemStatus.PENDING).count()
    if remaining == 0 and pool.status == OfferPoolStatus.ACTIVE:
        pool.status = OfferPoolStatus.DEPLETED
        pool.save(update_fields=['status', 'updated_at'])
        _log(
            PostingLogLevel.WARNING,
            f"Pool #{pool.pk} depleted — no pending items remain",
            account=pool.store,
            detail={'pool_id': pool.pk},
        )
