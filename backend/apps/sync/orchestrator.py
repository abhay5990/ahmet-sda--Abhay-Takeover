"""Cross-platform sync orchestrator.

Runs the full sync chain sequentially:
  1. LZT owned_products sync
  2. Offer sync (Eldorado, Gameboost, PlayerAuctions)
  3. Order sync (Eldorado, Gameboost, PlayerAuctions)
  4. Cross-platform reconciliation (offer removal + unlinked notification)

Called by APScheduler every N minutes via ``run_sync_chain()``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import clear_client_cache
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.sync.enums import ResourceType, SyncLogLevel, SyncMode, SyncPhase
from apps.sync.services.registry import build_service, get_service_class
from apps.sync.services.shared.feature_flags import SyncFlag, is_sync_feature_enabled
from apps.sync.services.shared.sync_log import log_sync, log_sync_error

if TYPE_CHECKING:
    from apps.sync.models import SyncRun

logger = logging.getLogger(__name__)

# Providers that have order + offer sync
_MARKETPLACE_PROVIDERS = ('eldorado', 'gameboost', 'playerauctions')


def _get_active_accounts(*providers: str) -> list[IntegrationAccount]:
    """Return active IntegrationAccounts with active credentials for given providers."""
    return list(
        IntegrationAccount.objects.select_related('credential', 'group').filter(
            provider__in=providers,
            is_active=True,
            credential__is_active=True,
        )
    )


def _sync_account(
    account: IntegrationAccount,
    resource_type: str,
    mode: str = SyncMode.INCREMENTAL,
    *,
    proxy_pool=None,
) -> 'SyncRun | None':
    """Run sync for a single account + resource type. Returns SyncRun or None."""
    if not get_service_class(resource_type, account.provider):
        return None
    group_name = get_group_name(account)
    service = build_service(
        resource_type, account.provider,
        credential=account.credential,
        proxy_pool=proxy_pool,
        proxy_group=group_name,
    )
    return service.run(account, mode=mode, phase=SyncPhase.FULL)


def sync_lzt(*, proxy_pool=None) -> None:
    """Sync LZT owned_products for all active LZT accounts."""
    if not is_sync_feature_enabled(SyncFlag.LZT):
        log_sync('lzt_sync', SyncLogLevel.INFO, 'LZT sync disabled via feature flag, skipping')
        return
    accounts = _get_active_accounts('lzt')
    for account in accounts:
        try:
            run = _sync_account(account, ResourceType.OWNED_PRODUCTS, proxy_pool=proxy_pool)
            if run:
                log_sync(
                    'lzt_sync', SyncLogLevel.SUCCESS,
                    f'{account.slug}: {run.created_count} created, {run.updated_count} updated',
                    sync_run=run, integration_account=account,
                )
        except Exception as e:
            log_sync_error('lzt_sync', f'{account.slug}: {e}', exc=e, integration_account=account)


def sync_offers(*, proxy_pool=None) -> None:
    """Sync offers/listings for all marketplace accounts."""
    if not is_sync_feature_enabled(SyncFlag.OFFERS):
        log_sync('offer_sync', SyncLogLevel.INFO, 'Offer sync disabled via feature flag, skipping')
        return
    accounts = _get_active_accounts(*_MARKETPLACE_PROVIDERS)
    for account in accounts:
        try:
            run = _sync_account(account, ResourceType.LISTINGS, proxy_pool=proxy_pool)
            if run:
                log_sync(
                    'offer_sync', SyncLogLevel.SUCCESS,
                    f'{account.slug}: {run.created_count} new, {run.updated_count} updated',
                    sync_run=run, integration_account=account,
                )
        except Exception as e:
            log_sync_error('offer_sync', f'{account.slug}: {e}', exc=e, integration_account=account)


def sync_orders(*, proxy_pool=None) -> list[int]:
    """Sync orders for all marketplace accounts.

    Returns list of newly *created* Order IDs (for cross-platform reconciliation).
    Only actionable orders are returned — cancelled, refunded, and disputed
    orders are excluded since they don't require offer removal.
    """
    from apps.orders.enums import OrderStatus
    from apps.orders.models import Order

    if not is_sync_feature_enabled(SyncFlag.ORDERS):
        log_sync('order_sync', SyncLogLevel.INFO, 'Order sync disabled via feature flag, skipping')
        return []

    chain_start = timezone.now()
    accounts = _get_active_accounts(*_MARKETPLACE_PROVIDERS)

    for account in accounts:
        try:
            run = _sync_account(account, ResourceType.ORDERS, proxy_pool=proxy_pool)
            # Also sync item orders (SAB, New World) for GameBoost accounts
            if account.provider == 'gameboost':
                try:
                    item_run = _sync_account(account, ResourceType.ITEM_ORDERS, proxy_pool=proxy_pool)
                    if item_run:
                        log_sync(
                            'order_sync', SyncLogLevel.SUCCESS,
                            f'{account.slug}: item orders — {item_run.created_count} new, {item_run.updated_count} updated',
                            sync_run=item_run, integration_account=account,
                        )
                except Exception as e:
                    log_sync_error('order_sync', f'{account.slug} item orders: {e}', exc=e, integration_account=account)
            if run:
                log_sync(
                    'order_sync', SyncLogLevel.SUCCESS,
                    f'{account.slug}: {run.created_count} new, {run.updated_count} updated',
                    sync_run=run, integration_account=account,
                )
        except Exception as e:
            log_sync_error('order_sync', f'{account.slug}: {e}', exc=e, integration_account=account)

    # Only newly created orders — updated orders were already reconciled
    new_order_ids = list(
        Order.objects.filter(
            created_at__gte=chain_start,
        ).exclude(
            status__in=[
                OrderStatus.CANCELLED,
                OrderStatus.REFUNDED,
                OrderStatus.DISPUTED,
            ],
        ).values_list('id', flat=True)
    )
    return new_order_ids


def run_sync_chain() -> None:
    """Main sync chain entry point — called by APScheduler.

    Runs sequentially: LZT → offers → orders → reconcile.
    Each step is wrapped in try/except so one failure doesn't block the rest.
    """
    log_sync('sync_chain', SyncLogLevel.INFO, 'Sync chain started')
    started = timezone.now()
    new_order_ids = []

    # Build proxy pool from DB and clear stale clients
    clear_client_cache()
    proxy_pool = build_proxy_pool()
    if proxy_pool:
        logger.info("Proxy pool ready: %d healthy proxies", proxy_pool.healthy_count)

    try:
        # 1. LZT sync (owned products source)
        try:
            sync_lzt(proxy_pool=proxy_pool)
        except Exception as e:
            log_sync_error('sync_chain', f'LZT sync phase failed: {e}', exc=e)

        # 2. Offer sync (all marketplaces)
        try:
            sync_offers(proxy_pool=proxy_pool)
        except Exception as e:
            log_sync_error('sync_chain', f'Offer sync phase failed: {e}', exc=e)

        # 3. Order sync (all marketplaces)
        try:
            new_order_ids = sync_orders(proxy_pool=proxy_pool)
        except Exception as e:
            log_sync_error('sync_chain', f'Order sync phase failed: {e}', exc=e)

        # 4. Cross-platform reconciliation
        if new_order_ids:
            try:
                from apps.sync.services.cross_platform import (
                    reconcile_cross_platform,
                    notify_unlinked_orders,
                )
                if is_sync_feature_enabled(SyncFlag.RECONCILE):
                    reconcile_cross_platform(new_order_ids)
                else:
                    log_sync('sync_chain', SyncLogLevel.INFO,
                             f'Reconciliation disabled via feature flag, skipping '
                             f'({len(new_order_ids)} orders not reconciled)')

                if is_sync_feature_enabled(SyncFlag.UNLINKED_NOTIFY):
                    notify_unlinked_orders(new_order_ids)
            except Exception as e:
                log_sync_error('sync_chain', f'Reconciliation phase failed: {e}', exc=e)

        # 5. Eldorado notification → order status sync (runs after orders exist)
        if is_sync_feature_enabled(SyncFlag.ELDORADO_NOTIFICATIONS):
            try:
                from apps.sync.services.eldorado.notifications.status_sync import (
                    EldoradoNotificationStatusSync,
                )
                EldoradoNotificationStatusSync().run()
            except Exception as e:
                log_sync_error('sync_chain', f'Notification status sync failed: {e}', exc=e)

        # 6. Robux auto-fulfillment detection — runs immediately after order sync
        # so new Roblox currency orders trigger Telegram within seconds, not up to 5 min later
        try:
            import os
            if os.environ.get('ROBLOX_NOTIFY_PAUSED', '').lower() not in ('true', '1', 'yes'):
                from apps.tools.services.robux_auto_fulfillment import detect_new_roblox_orders
                detected = detect_new_roblox_orders()
                if detected:
                    logger.info('sync_chain: robux_auto detected %d new order(s) post-sync', detected)
        except Exception as e:
            log_sync_error('sync_chain', f'Robux post-sync detection failed: {e}', exc=e)
    finally:
        clear_client_cache()

    elapsed = (timezone.now() - started).total_seconds()
    log_sync(
        'sync_chain', SyncLogLevel.SUCCESS,
        f'Sync chain completed in {elapsed:.0f}s ({len(new_order_ids)} orders processed)',
    )
