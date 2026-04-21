"""Dropship cleaner — continuous loop driven by the scheduler service.

Public entry point: ``cleaner_loop(cleaner_config, stop_event)``
Called by the scheduler's cleaner thread wrapper.  Raises ``PauseRequired``
when error thresholds are exceeded; the wrapper catches it and sets
``enabled=False`` with a reason.

Each cleaner instance is scoped to a single source account — it checks all
DropshipProducts belonging to that source, regardless of target store/game.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from threading import Event

from django.utils import timezone

from apps.integrations.providers import registry
from apps.integrations.proxy_pool import get_group_name
from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import (
    CleanerConfig,
    PostingLog,
    PostingLogLevel,
)
from apps.posting.services.dropship.backoff import (
    ErrorTracker,
    PauseRequired,
    classify_api_error,
)
from apps.posting.services.dropship.source_provider import get_source_provider

# Ensure all source providers are registered
import apps.posting.services.dropship.sources  # noqa: F401

logger = logging.getLogger(__name__)

# Default delay between source checks (seconds)
DEFAULT_CHECK_DELAY = 1.0

# How long to sleep when LZT is in maintenance mode (seconds)
MAINTENANCE_WAIT = 120.0


class _MaintenanceDetected(Exception):
    """Internal signal — source platform is in maintenance mode."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cleaner_loop(cleaner_config: CleanerConfig, stop_event: Event) -> None:
    """Continuous cleaner loop — called by the scheduler thread wrapper.

    * Scoped to ``cleaner_config.source_account`` — checks all its DPs.
    * Each cycle: query LISTED DPs for this source, check each against source.
    * After each cycle: wait ``cycle_interval`` (interruptible).
    * Raises ``PauseRequired`` when ErrorTracker thresholds are hit.
    * Returns normally when ``stop_event`` is set (user disable / shutdown).
    """
    tracker = ErrorTracker(stop_event=stop_event)
    source_account = cleaner_config.source_account

    # Build source provider once — reused across all products for this source
    source_type = source_account.provider
    source_provider = get_source_provider(source_type, source_account.credential)
    proxy_group = get_group_name(source_account)

    while not stop_event.is_set():

        # Refresh cleaner flags from DB at cycle start
        cleaner_config.refresh_from_db(fields=['enabled', 'cycle_interval'])
        if not cleaner_config.enabled:
            break

        listed_products = (
            DropshipProduct.objects
            .filter(
                status=DropshipProductStatus.LISTED,
                source_account=source_account,
            )
            .select_related(
                'source_account', 'source_account__credential',
                'game', 'category',
            )
            .order_by('last_checked_at')  # oldest-checked first
        )

        for dp in listed_products:
            if stop_event.is_set():
                break

            # DB stop check before each product
            cleaner_config.refresh_from_db(fields=['enabled'])
            if not cleaner_config.enabled:
                stop_event.set()
                break

            try:
                _check_single_product(
                    dp, tracker=tracker,
                    source_provider=source_provider, proxy_group=proxy_group,
                )
            except PauseRequired:
                raise  # propagate to wrapper
            except _MaintenanceDetected:
                # Platform maintenance — skip remaining products, wait, retry cycle
                stop_event.wait(timeout=MAINTENANCE_WAIT)
                break
            except Exception as e:
                logger.exception("Cleaner failed for DropshipProduct #%d: %s", dp.id, e)
                PostingLog.objects.create(
                    task_name='dropship_cleaner',
                    level=PostingLogLevel.ERROR,
                    message=f"Check failed: {dp.source_product_id}",
                    detail={'dropship_product_id': dp.id, 'error': str(e)},
                    integration_account=dp.source_account,
                )

            stop_event.wait(timeout=DEFAULT_CHECK_DELAY)

        # --- Cycle end ---
        cleaner_config.last_cycle_at = timezone.now()
        cleaner_config.save(update_fields=['last_cycle_at'])
        stop_event.wait(timeout=float(cleaner_config.cycle_interval))


# ---------------------------------------------------------------------------
# Single product check
# ---------------------------------------------------------------------------

def _check_single_product(
    dp: DropshipProduct,
    *,
    tracker: ErrorTracker,
    source_provider,
    proxy_group: str | None,
) -> None:
    """Check a single dropship product against its source platform.

    Raises PauseRequired via tracker when error thresholds are hit.
    """
    # Check item on source platform
    check = source_provider.check_item(
        str(dp.source_product_id), proxy_group=proxy_group,
    )

    # Handle API errors (status='api_error' means the API call itself failed)
    if check.status == 'api_error':
        api_result = check.raw_data.get('api_result')
        if api_result is not None:
            error_type = classify_api_error(api_result)

            if error_type == 'maintenance':
                # LZT is in scheduled maintenance — don't count as error,
                # just wait and let the cycle retry after the window passes.
                logger.info(
                    "LZT maintenance detected — waiting %ds before next check",
                    int(MAINTENANCE_WAIT),
                )
                PostingLog.objects.create(
                    task_name='dropship_cleaner',
                    level=PostingLogLevel.INFO,
                    message="LZT maintenance — pausing checks",
                    detail={'wait_seconds': MAINTENANCE_WAIT},
                    integration_account=dp.source_account,
                )
                raise _MaintenanceDetected()

            if error_type == 'rate_limit':
                tracker.on_rate_limit()
                return

            if error_type == 'server':
                tracker.on_server_error()
                return

            if error_type in ('not_found', 'auth'):
                _handle_item_gone(dp, reason='deleted')
                return

            # Other API errors — log and skip
            error_cat = api_result.error.category if api_result.error else 'UNKNOWN'
            logger.warning(
                "Source check failed for item %d: %s (category=%s)",
                dp.source_product_id, api_result.error, error_cat,
            )
            PostingLog.objects.create(
                task_name='dropship_cleaner',
                level=PostingLogLevel.WARNING,
                message=f"Source check failed: item {dp.source_product_id} ({error_cat})",
                detail={
                    'dropship_product_id': dp.id,
                    'source_product_id': dp.source_product_id,
                    'error': str(api_result.error),
                    'error_category': str(error_cat),
                },
                integration_account=dp.source_account,
            )
        return

    # Success — reset error counters
    tracker.on_success()

    # Item gone (sold/closed/deleted)
    if not check.exists:
        _handle_item_gone(dp, reason=check.status or 'deleted')
        return

    # Check price change — only act if price moved more than 3% from
    # the price recorded when the DP was first posted.  Small fluctuations
    # (floating-point noise, minor marketplace adjustments) are ignored.
    if (
        check.current_price
        and check.current_price > 0
        and dp.price > 0
    ):
        pct_change = abs(check.current_price - dp.price) / dp.price
        if pct_change > Decimal('0.03'):
            _handle_price_change(dp, check.current_price, check.raw_data)
            return

    # No change (or within tolerance) — just update last_checked_at
    dp.last_checked_at = timezone.now()
    dp.save(update_fields=['last_checked_at'])


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _remove_all_offers(dp: DropshipProduct) -> bool:
    """Delete all LISTED marketplace offers for a DropshipProduct.

    Returns True if all offers were removed, False if any failed (retry next cycle).
    """
    listings = Listing.objects.filter(
        dropship_product=dp,
        status=ListingStatus.LISTED,
    ).select_related('integration_account', 'integration_account__credential')

    all_deleted = True
    for listing in listings:
        if not _delete_marketplace_offer(listing):
            all_deleted = False

    if not all_deleted:
        dp.last_checked_at = timezone.now()
        dp.save(update_fields=['last_checked_at'])

    return all_deleted


def _handle_item_gone(dp: DropshipProduct, *, reason: str) -> None:
    """Item sold/deleted on source — delete marketplace offer, update status."""
    if not _remove_all_offers(dp):
        return

    new_status = (
        DropshipProductStatus.SOLD if reason in ('sold', 'closed')
        else DropshipProductStatus.DELETED
    )
    dp.status = new_status
    dp.last_checked_at = timezone.now()
    dp.deleted_at = timezone.now()
    dp.save(update_fields=['status', 'last_checked_at', 'deleted_at'])

    PostingLog.objects.create(
        task_name='dropship_cleaner',
        level=PostingLogLevel.INFO,
        message=f"Item {dp.source_product_id} {reason} — offer removed",
        detail={
            'dropship_product_id': dp.id,
            'source_product_id': dp.source_product_id,
            'reason': reason,
        },
        integration_account=dp.source_account,
    )


def _handle_price_change(
    dp: DropshipProduct, new_price: Decimal, item_data: dict,
) -> None:
    """Price changed on source — delete marketplace offers, mark DP as DELETED."""
    old_price = dp.price

    if not _remove_all_offers(dp):
        return

    dp.status = DropshipProductStatus.DELETED
    dp.price = new_price
    dp.raw_data = item_data
    dp.last_checked_at = timezone.now()
    dp.deleted_at = timezone.now()
    dp.save(update_fields=['status', 'price', 'raw_data', 'last_checked_at', 'deleted_at'])

    PostingLog.objects.create(
        task_name='dropship_cleaner',
        level=PostingLogLevel.INFO,
        message=f"Price changed: item {dp.source_product_id} {old_price}→{new_price} — offer removed, awaiting re-post",
        detail={
            'dropship_product_id': dp.id,
            'source_product_id': dp.source_product_id,
            'old_price': str(old_price),
            'new_price': str(new_price),
        },
        integration_account=dp.source_account,
    )


def _delete_marketplace_offer(listing: Listing) -> bool:
    """Delete an offer from the marketplace and update listing status.

    Returns True if the offer was successfully deleted (or store is gone),
    False if the API call failed — listing stays LISTED so the next cycle
    can retry.
    """
    store = listing.integration_account
    if not store or not store.credential:
        # Store gone — mark closed, nothing to delete remotely
        listing.status = ListingStatus.CLOSED
        listing.removed_at = timezone.now()
        listing.save(update_fields=['status', 'removed_at'])
        return True

    marketplace = store.provider
    try:
        provider = registry.get_provider(marketplace)
        facade = registry.get_or_build_client(marketplace, store.credential)
        provider.delete_listing(facade, listing.store_listing_id)
    except Exception as e:
        logger.warning(
            "Failed to delete offer %s on %s: %s",
            listing.store_listing_id, marketplace, e,
        )
        PostingLog.objects.create(
            task_name='dropship_cleaner',
            level=PostingLogLevel.ERROR,
            message=f"Delete offer failed: {listing.store_listing_id} on {marketplace}",
            detail={
                'listing_id': listing.id,
                'store_listing_id': listing.store_listing_id,
                'marketplace': marketplace,
                'error': str(e),
            },
            integration_account=store,
        )
        # Keep listing LISTED — next cleaner cycle will retry
        return False

    listing.status = ListingStatus.CLOSED
    listing.removed_at = timezone.now()
    listing.save(update_fields=['status', 'removed_at'])
    return True
