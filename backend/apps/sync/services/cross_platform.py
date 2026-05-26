"""Cross-platform reconciliation service.

When an order is matched to an OwnedProduct, this service:
  1. Finds all listings for that OwnedProduct on OTHER platforms
  2. For single-account listings: removes/deletes them via platform API
  3. For multi-account listings (platform-specific):
     - Eldorado: delete old offer → create new without sold credential
     - Gameboost non-legacy: delete credential via credentials API (offer stays)
     - Gameboost legacy: delete old offer → create new without sold credential
     - PlayerAuctions: always single-account, direct delete
  4. Updates OwnedProduct status to SOLD
  5. Logs all actions to SyncLog

Legacy detection (Gameboost):
  - credentials.login is null → non-legacy (credentials API available)
  - credentials.login is filled → legacy (must delete + recreate)
"""

from __future__ import annotations

import logging
from itertools import groupby
from operator import attrgetter
from typing import Any

from django.db import transaction
from django.utils import timezone

from apis_sdk.clients.marketplaces.eldorado.mapper import EldoradoMapper
from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.sync.enums import SyncLogLevel
from apps.sync.models import RawPayload
from apps.sync.services.shared.credentials import parse_credentials_text
from apps.sync.services.shared.sync_log import log_sync, log_sync_error
from core.marketplace.normalizers import normalize_offer_response

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────


def reconcile_cross_platform(order_ids: list[int]) -> None:
    """Process newly synced orders: remove cross-platform offers and update statuses."""
    orders = (
        Order.objects.filter(
            id__in=order_ids,
            owned_product__isnull=False,
            is_instant=True,
        )
        .exclude(status=OrderStatus.CANCELLED)
        .select_related('owned_product', 'integration_account')
    )

    for order in orders:
        try:
            _reconcile_single_order(order)
        except Exception as e:
            log_sync_error(
                'reconcile',
                f'Order #{order.store_order_id}: {e}',
                exc=e,
                order=order,
                owned_product=order.owned_product,
            )


def notify_unlinked_orders(order_ids: list[int]) -> None:
    """Log warnings for instant orders that couldn't be matched to an OwnedProduct."""
    unlinked = (
        Order.objects.filter(
            id__in=order_ids,
            owned_product__isnull=True,
            is_instant=True,
        )
        .exclude(status=OrderStatus.CANCELLED)
        .select_related('integration_account')
    )

    for order in unlinked:
        log_sync(
            'unlinked_order', SyncLogLevel.WARNING,
            f'Order #{order.store_order_id} ({order.integration_account.slug}) '
            f'— OwnedProduct not matched',
            order=order,
            integration_account=order.integration_account,
            detail={
                'store_order_id': order.store_order_id,
                'price': str(order.price) if order.price else None,
                'status': order.status,
            },
        )


# ── Order-level reconciliation ─────────────────────────────────────


def _reconcile_single_order(order: Order) -> None:
    """For a single order: find cross-platform offers and handle them safely."""
    owned = order.owned_product
    sale_account = order.integration_account

    cross_listings = (
        Listing.objects.filter(
            listing_owned_products__owned_product=owned,
            status__in=[ListingStatus.LISTED, ListingStatus.PAUSED],
        )
        .exclude(integration_account=sale_account)
        .select_related('integration_account__credential')
    )

    if not cross_listings.exists():
        _update_owned_product_sold(owned)
        return

    reconciled_count = 0
    sorted_listings = sorted(cross_listings, key=attrgetter('integration_account_id'))

    for _account_id, group in groupby(sorted_listings, key=attrgetter('integration_account_id')):
        listings = list(group)
        account = listings[0].integration_account
        client = get_or_build_client(account.provider, account.credential)

        for listing in listings:
            try:
                if _is_multi_account(listing):
                    _reconcile_multi_account(listing, owned, account, client, order)
                else:
                    _remove_single_offer(listing, account, client)
                reconciled_count += 1
                log_sync(
                    'offer_removal', SyncLogLevel.SUCCESS,
                    f'Reconciled {listing.store_listing_id} from {account.slug} '
                    f'(provider={account.provider})',
                    listing=listing,
                    owned_product=owned,
                    order=order,
                    integration_account=account,
                )
            except Exception as e:
                log_sync_error(
                    'offer_removal',
                    f'Failed to reconcile {listing.store_listing_id} '
                    f'from {account.slug}: {e}',
                    exc=e,
                    listing=listing,
                    owned_product=owned,
                    order=order,
                )

    _update_owned_product_sold(owned)

    if reconciled_count:
        log_sync(
            'reconcile', SyncLogLevel.SUCCESS,
            f'Order #{order.store_order_id}: reconciled {reconciled_count} cross-platform offer(s)',
            order=order,
            owned_product=owned,
            detail={'reconciled_count': reconciled_count},
        )


# ── Multi-account dispatch ─────────────────────────────────────────


def _is_multi_account(listing: Listing) -> bool:
    """Check if a listing has more than one linked OwnedProduct."""
    return listing.listing_owned_products.count() > 1


def _reconcile_multi_account(
    listing: Listing,
    sold_owned: Any,
    account: Any,
    client: Any,
    order: Order,
) -> None:
    """Dispatch multi-account reconciliation to platform-specific handler."""
    all_lops = ListingOwnedProduct.objects.filter(
        listing=listing,
    ).select_related('owned_product')

    remaining = [lop.owned_product for lop in all_lops if lop.owned_product_id != sold_owned.id]

    if not remaining:
        _remove_single_offer(listing, account, client)
        return

    provider_name = account.provider
    if provider_name == 'eldorado':
        _reconcile_eldorado(listing, sold_owned, remaining, account, client)
    elif provider_name == 'gameboost':
        _reconcile_gameboost(listing, sold_owned, remaining, account, client)
    else:
        log_sync(
            'offer_removal', SyncLogLevel.WARNING,
            f'Multi-account listing {listing.store_listing_id}: '
            f'provider {provider_name} has no multi-account strategy, skipping',
            listing=listing,
            integration_account=account,
            detail={'remaining_count': len(remaining), 'reason': 'unsupported_provider'},
        )


# ── Eldorado: delete old → create new without sold credential ──────


def _reconcile_eldorado(
    listing: Listing,
    sold_owned: Any,
    remaining: list,
    account: Any,
    client: Any,
) -> None:
    """Eldorado multi-account: create new offer first → delete old after.

    Safe order: create replacement first, then delete old. If create fails,
    old offer stays intact — no offer loss.
    """
    raw_payload = _get_raw_payload(listing, account)
    if raw_payload is None:
        return
    raw_data = raw_payload.payload

    # Find credential IDs to exclude (sold account)
    exclude_ids = _find_eldorado_sold_credential_ids(raw_data, sold_owned.login)

    # Build new payload without sold credentials
    payload = EldoradoMapper.build_from_raw(raw_data, exclude_credential_ids=exclude_ids)
    new_cred_count = len(payload.get("accountSecretDetails", []))

    if new_cred_count == 0:
        logger.warning(
            'build_from_raw produced 0 credentials for listing %s — deleting whole offer',
            listing.store_listing_id,
        )
        _remove_single_offer(listing, account, client)
        return

    # Step 1: Create new offer FIRST (old offer stays intact if this fails)
    result = client.create_offer(payload)

    if not result.ok:
        raise RuntimeError(
            f'Failed to create replacement offer for {listing.store_listing_id}: '
            f'{result.error}. Old offer left intact.'
        )

    new_offer = result.data
    new_offer_id = new_offer.id if new_offer else 'unknown'

    # Step 2: Delete old offer (new offer already exists as safety net)
    try:
        provider = get_provider(account.provider)
        provider.delete_listing(client, listing.store_listing_id)
    except Exception as e:
        logger.warning(
            'New offer %s created but failed to delete old offer %s: %s. '
            'Old offer may need manual cleanup.',
            new_offer_id, listing.store_listing_id, e,
        )

    # Step 3: Update DB atomically
    _replace_listing_in_db(listing, new_offer_id, remaining, new_offer, payload=payload)

    logger.info(
        'Eldorado reconcile: %s → %s (%d credentials)',
        listing.store_listing_id, new_offer_id, new_cred_count,
    )


def _find_eldorado_sold_credential_ids(raw_data: dict, sold_login: str) -> set:
    """Match sold login to Eldorado credential entry IDs.

    Uses the shared credential parser to handle all formats (arrow, tab,
    colon, labeled lines, etc.) instead of only arrow format.
    """
    sold_login_lower = sold_login.lower().strip()
    credential_entries = raw_data.get("_credential_entries") or []
    exclude_ids: set = set()

    for entry in credential_entries:
        secret = entry.get("secretDetails", "")
        if not secret:
            continue
        parsed = parse_credentials_text(secret)
        if parsed.login and parsed.login.lower().strip() == sold_login_lower:
            exclude_ids.add(entry["id"])

    return exclude_ids


# ── Gameboost: legacy detection + platform-specific handling ───────


def _is_gameboost_legacy(raw_data: dict) -> bool:
    """Detect if a Gameboost offer is legacy format.

    Legacy: credentials.login is filled (single credential embedded in offer).
    Non-legacy: credentials.login is null (credentials managed via API).
    """
    credentials = raw_data.get("credentials")
    if not isinstance(credentials, dict):
        return True  # no credentials info → treat as legacy (safer)
    return bool(credentials.get("login"))


def _reconcile_gameboost(
    listing: Listing,
    sold_owned: Any,
    remaining: list,
    account: Any,
    client: Any,
) -> None:
    """Gameboost multi-account dispatch: legacy vs non-legacy."""
    raw_payload = _get_raw_payload(listing, account)
    if raw_payload is None:
        return
    raw_data = raw_payload.payload

    if _is_gameboost_legacy(raw_data):
        _reconcile_gameboost_legacy(listing, sold_owned, remaining, account, client, raw_data)
    else:
        _reconcile_gameboost_credentials(listing, sold_owned, account, client, raw_data)


def _reconcile_gameboost_credentials(
    listing: Listing,
    sold_owned: Any,
    account: Any,
    client: Any,
    raw_data: dict,
) -> None:
    """Gameboost non-legacy: delete sold credential via API, offer stays intact."""
    sold_login = sold_owned.login.lower().strip()
    credential_entries = raw_data.get("_credential_entries") or []
    matched_credential_id = None

    for entry in credential_entries:
        cred_text = entry.get("credentials", "")
        if not cred_text:
            continue
        parsed = parse_credentials_text(cred_text)
        if parsed.login and parsed.login.lower().strip() == sold_login:
            matched_credential_id = entry.get("id")
            break

    if not matched_credential_id:
        log_sync(
            'offer_removal', SyncLogLevel.WARNING,
            f'Gameboost listing {listing.store_listing_id}: could not match '
            f'sold login to credential entry, skipping',
            listing=listing,
            integration_account=account,
            detail={'sold_login': sold_login, 'reason': 'no_credential_match'},
        )
        return

    result = client.delete_offer_credential(
        account_id=listing.store_listing_id,
        credential_id=str(matched_credential_id),
    )

    if not result.ok:
        error_msg = str(result.error) if result.error else ''
        # Gameboost returns "Cannot delete sold items" for already-sold credentials.
        # API already knows it's sold — just clean up DB linkage.
        if 'cannot delete sold' in error_msg.lower():
            logger.info(
                'Gameboost credential %s already sold on API side for offer %s '
                '(login=%s) — unlinking from DB only',
                matched_credential_id, listing.store_listing_id, sold_owned.login,
            )
        else:
            raise RuntimeError(
                f'Failed to delete credential {matched_credential_id} from '
                f'offer {listing.store_listing_id}: {result.error}'
            )

    # Unlink sold OwnedProduct — listing stays LISTED
    ListingOwnedProduct.objects.filter(
        listing=listing,
        owned_product=sold_owned,
    ).delete()

    logger.info(
        'Gameboost credential removed: offer %s, credential %s (login=%s)',
        listing.store_listing_id, matched_credential_id, sold_owned.login,
    )


def _reconcile_gameboost_legacy(
    listing: Listing,
    sold_owned: Any,
    remaining: list,
    account: Any,
    client: Any,  # noqa: ARG001 — reserved for future legacy recreate
    raw_data: dict,  # noqa: ARG001 — reserved for future legacy recreate
) -> None:
    """Gameboost legacy: credentials API not available → log warning, skip.

    Legacy offers have a single credential embedded in the offer.
    Multi-account legacy offers should not exist, but if they do,
    we skip and log for manual intervention — recreating Gameboost offers
    requires template knowledge (TASK-023).
    """
    log_sync(
        'offer_removal', SyncLogLevel.WARNING,
        f'Gameboost legacy listing {listing.store_listing_id}: '
        f'credentials API not available, skipping multi-account reconcile. '
        f'Manual intervention required.',
        listing=listing,
        integration_account=account,
        detail={
            'remaining_count': len(remaining),
            'reason': 'legacy_no_credentials_api',
            'sold_login': sold_owned.login,
        },
    )


# ── Shared helpers ─────────────────────────────────────────────────


def _get_raw_payload(listing: Listing, account: Any) -> RawPayload | None:
    """Load RawPayload for a listing. Returns None and logs warning if not found."""
    try:
        return RawPayload.objects.get(
            integration_account=account,
            resource_type='listings',
            remote_id=listing.store_listing_id,
        )
    except RawPayload.DoesNotExist:
        remaining_count = listing.listing_owned_products.count()
        log_sync(
            'offer_removal', SyncLogLevel.WARNING,
            f'Multi-account listing {listing.store_listing_id}: no RawPayload, skipping '
            f'(would lose {remaining_count} accounts)',
            listing=listing,
            integration_account=account,
            detail={'remaining_count': remaining_count, 'reason': 'no_raw_payload'},
        )
        return None


def _remove_single_offer(listing: Listing, account: Any = None, client: Any = None) -> None:
    """Remove a single-account offer via platform API and update DB status."""
    if account is None:
        account = listing.integration_account
    provider = get_provider(account.provider)
    if client is None:
        client = get_or_build_client(account.provider, account.credential)

    provider.delete_listing(client, listing.store_listing_id)

    listing.status = ListingStatus.DELETED
    listing.removed_at = timezone.now()
    listing.save(update_fields=['status', 'removed_at', 'updated_at'])


def _replace_listing_in_db(
    old_listing: Listing,
    new_offer_id: Any,
    remaining_owned_products: list,
    new_offer: Any = None,
    *,
    payload: dict | None = None,
) -> None:
    """Atomically replace old listing with new one and update OwnedProduct links."""
    with transaction.atomic():
        # Mark old listing as deleted and clear links
        ListingOwnedProduct.objects.filter(listing=old_listing).delete()
        old_listing.status = ListingStatus.DELETED
        old_listing.removed_at = timezone.now()
        old_listing.save(update_fields=['status', 'removed_at', 'updated_at'])

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
            last_synced_at=timezone.now(),
            is_instant=old_listing.is_instant,
            raw_data=(
                normalize_offer_response('eldorado', new_offer, payload=payload)
                if new_offer else {}
            ),
        )

        # Link remaining OwnedProducts to new listing
        ListingOwnedProduct.objects.bulk_create([
            ListingOwnedProduct(listing=new_listing, owned_product=op)
            for op in remaining_owned_products
        ])

    return new_listing


def _update_owned_product_sold(owned: Any) -> None:
    """Update OwnedProduct status via central resolver."""
    from apps.inventory.services import resolve_owned_product_status
    resolve_owned_product_status(owned)
