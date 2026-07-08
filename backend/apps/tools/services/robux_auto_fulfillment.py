"""
Automated Robux delivery service via Telegram bot.

Flow:
1. Detect new Roblox currency orders (Eldorado/GameBoost) not yet tracked
2. Send Telegram notification to staff asking for buyer's Roblox username
3. Poll Telegram for staff reply (getUpdates)
4. On reply: look up buyer's Roblox Place ID via Roblox API
5. Create RobuxCrateBatch + orders automatically
6. Delivery is handled by the existing robuxcrate batch processor

State machine:
  awaiting_username → (staff replies) → username_received
  username_received → (place lookup) → order_created | place_lookup_failed
  order_created → (batch processor) → delivered
  failed / skipped — terminal error states
"""
from __future__ import annotations

import logging
import uuid as uuid_lib

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_ROBLOX_GAME_SLUG = 'roblox'


# ── Telegram helpers ─────────────────────────────────────────────────────────

def _get_telegram_creds():
    """Return (bot_token, chat_id) or (None, None)."""
    try:
        from apps.integrations.models import ServiceCredential
        cred = ServiceCredential.objects.filter(
            service_type='telegram', is_active=True
        ).first()
        if not cred:
            return None, None
        creds = cred.credentials or {}
        return creds.get('bot_token', ''), creds.get('chat_id', '')
    except Exception as exc:
        logger.error('robux_auto: failed to get Telegram creds: %s', exc)
        return None, None


def _telegram_send(bot_token: str, chat_id: str, text: str) -> int | None:
    """Send a Telegram message. Returns message_id or None."""
    import requests
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            json={'chat_id': chat_id, 'text': text},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get('result', {}).get('message_id')
    except Exception as exc:
        logger.warning('robux_auto: Telegram send failed: %s', exc)
    return None


def _telegram_get_updates(bot_token: str, offset: int | None = None) -> list[dict]:
    """Fetch Telegram updates via getUpdates."""
    import requests
    params: dict = {'timeout': 0, 'allowed_updates': ['message']}
    if offset is not None:
        params['offset'] = offset
    try:
        resp = requests.get(
            f'https://api.telegram.org/bot{bot_token}/getUpdates',
            params=params,
            timeout=10,
        )
        if resp.ok:
            return resp.json().get('result', [])
    except Exception as exc:
        logger.warning('robux_auto: getUpdates failed: %s', exc)
    return []


# ── Roblox helper ────────────────────────────────────────────────────────────

def _get_roblox_client():
    """Return a RobloxFacade or None."""
    try:
        from apps.integrations.models import ServiceCredential
        from apps.integrations.services.registry import get_service
        cred = ServiceCredential.objects.filter(
            service_type='roblox', is_active=True
        ).first()
        if not cred:
            return None
        service = get_service('roblox')
        if not service:
            return None
        return service.build_client(cred)
    except Exception as exc:
        logger.error('robux_auto: failed to build Roblox client: %s', exc)
        return None


def _get_robuxcrate_merchant():
    """Return the first active RbxCrate ServiceCredential or None."""
    try:
        from apps.integrations.models import ServiceCredential
        return ServiceCredential.objects.filter(
            service_type='robuxcrate', is_active=True
        ).first()
    except Exception:
        return None


# ── Robux amount extraction ──────────────────────────────────────────────────

def _parse_robux_amount_from_order(order) -> int:
    """Extract Robux amount from the order's raw_data or price."""
    rd = order.raw_data or {}
    # Eldorado currency orders: purchaseQuantity = number of Robux units
    qty = rd.get('purchaseQuantity')
    if qty:
        try:
            return int(qty)
        except (ValueError, TypeError):
            pass
    # Fallback: price in USD * 80 (rough estimate: $1 ≈ 80 Robux)
    try:
        price = float(order.price or 0)
        if price > 0:
            return max(100, int(price * 80))
    except (ValueError, TypeError):
        pass
    return 800  # safe default


# ── Phase 1: Detect new Roblox orders ────────────────────────────────────────

def detect_new_roblox_orders() -> int:
    """Find new Roblox currency orders not yet tracked.
    Creates RobuxAutoOrder records and sends Telegram notifications.
    Returns count of new orders detected.
    """
    from apps.orders.models import Order
    from apps.tools.models import RobuxAutoOrder
    from core.enums import ProductCategory

    bot_token, chat_id = _get_telegram_creds()
    if not bot_token or not chat_id:
        logger.warning('robux_auto: Telegram not configured — skipping detection')
        return 0

    # Find tracked order IDs to exclude
    tracked_ids = set(RobuxAutoOrder.objects.values_list('order_id', flat=True))

    new_orders = (
        Order.objects
        .filter(
            product_category=ProductCategory.CURRENCY,
            game__slug=_ROBLOX_GAME_SLUG,
            status__in=['pending', 'in_progress', 'active'],
        )
        .exclude(id__in=tracked_ids)
        .select_related('integration_account', 'game')
    )

    count = 0
    for order in new_orders:
        try:
            rd = order.raw_data or {}
            buyer = rd.get('buyerUsername') or rd.get('buyer_username') or 'Unknown'
            store = str(order.integration_account) if order.integration_account else 'Unknown'
            robux = _parse_robux_amount_from_order(order)

            text = (
                f"\U0001f3ae New Robux Order \u2014 Action Required\n\n"
                f"Order  : {order.store_order_id}\n"
                f"Store  : {store}\n"
                f"Buyer  : {buyer}\n"
                f"Amount : {robux:,} R$\n\n"
                f"Reply to this message with the buyer's Roblox username to auto-deliver."
            )
            msg_id = _telegram_send(bot_token, chat_id, text)

            RobuxAutoOrder.objects.create(
                order=order,
                state='awaiting_username',
                telegram_message_id=msg_id,
                notified_at=timezone.now(),
            )
            count += 1
            logger.info('robux_auto: created RobuxAutoOrder for order %s', order.store_order_id)
        except Exception as exc:
            logger.error('robux_auto: failed to create RobuxAutoOrder for order %s: %s', order.store_order_id, exc)

    return count


# ── Phase 2: Process Telegram replies ────────────────────────────────────────

def process_telegram_replies() -> int:
    """Poll Telegram for staff replies and update states.
    Returns count of replies processed.
    """
    from apps.tools.models import RobuxAutoOrder

    bot_token, chat_id = _get_telegram_creds()
    if not bot_token:
        return 0

    pending = RobuxAutoOrder.objects.filter(
        state='awaiting_username',
        telegram_message_id__isnull=False,
    ).select_related('order')

    if not pending.exists():
        return 0

    # Build map: telegram_message_id → RobuxAutoOrder
    msg_map = {ao.telegram_message_id: ao for ao in pending}

    updates = _telegram_get_updates(bot_token)
    count = 0

    for update in updates:
        msg = update.get('message', {})
        if not msg:
            continue

        reply_to = msg.get('reply_to_message', {})
        reply_to_id = reply_to.get('message_id') if reply_to else None

        if reply_to_id and reply_to_id in msg_map:
            auto_order = msg_map[reply_to_id]
            text = (msg.get('text') or '').strip()
            if not text:
                continue

            # Extract Roblox username — first word, strip @
            username = text.split()[0].lstrip('@').strip()
            if not username:
                continue

            auto_order.roblox_username = username
            auto_order.state = 'username_received'
            auto_order.username_received_at = timezone.now()
            auto_order.save(update_fields=['roblox_username', 'state', 'username_received_at', 'updated_at'])
            logger.info('robux_auto: received username "%s" for order %s', username, auto_order.order.store_order_id)
            count += 1

    return count


# ── Phase 3: Create RbxCrate batch ───────────────────────────────────────────

def process_username_received_orders() -> int:
    """For orders with username received, look up Place ID and create RbxCrate batch.
    Returns count of orders processed.
    """
    from apps.tools.models import RobuxAutoOrder, RobuxCrateBatch, RobuxCrateOrder

    pending = RobuxAutoOrder.objects.filter(
        state='username_received',
    ).select_related('order', 'order__integration_account', 'order__integration_account__credential')

    if not pending.exists():
        return 0

    roblox_client = _get_roblox_client()
    merchant = _get_robuxcrate_merchant()
    bot_token, chat_id = _get_telegram_creds()

    if not merchant:
        logger.warning('robux_auto: no active RbxCrate merchant — skipping')
        return 0

    count = 0
    for auto_order in pending:
        order = auto_order.order
        username = auto_order.roblox_username

        try:
            # Look up Roblox user and places
            place_candidates = []
            roblox_user_id = ''

            if roblox_client:
                result = roblox_client.lookup_user_with_places(username)
                if result.ok and result.data:
                    lookup = result.data
                    roblox_user_id = str(lookup.user.user_id)
                    place_candidates = [
                        {'place_id': p.place_id, 'name': p.name}
                        for p in lookup.places
                    ]
                else:
                    err = result.error.message if result.error else 'Unknown error'
                    logger.warning('robux_auto: Roblox lookup failed for "%s": %s', username, err)
                    auto_order.error_message = f'Roblox lookup failed: {err}'
                    auto_order.state = 'place_lookup_failed'
                    auto_order.save(update_fields=['error_message', 'state', 'updated_at'])
                    if bot_token and chat_id:
                        _telegram_send(bot_token, chat_id,
                            f"\u26a0\ufe0f Robux Auto-Delivery \u2014 Lookup Failed\n\n"
                            f"Order   : {order.store_order_id}\n"
                            f"Username: {username}\n"
                            f"Error   : {err}\n\n"
                            f"Please create the order manually in the RobuxCrate tool."
                        )
                    continue

            if not place_candidates:
                auto_order.error_message = f'No public games found for "{username}"'
                auto_order.state = 'place_lookup_failed'
                auto_order.save(update_fields=['error_message', 'state', 'updated_at'])
                if bot_token and chat_id:
                    _telegram_send(bot_token, chat_id,
                        f"\u26a0\ufe0f Robux Auto-Delivery \u2014 No Games Found\n\n"
                        f"Order   : {order.store_order_id}\n"
                        f"Username: {username}\n"
                        f"Error   : No public games found on this account.\n\n"
                        f"Please create the order manually in the RobuxCrate tool."
                    )
                continue

            robux_amount = _parse_robux_amount_from_order(order)

            # Get the IntegrationCredential for the store
            store_cred = None
            if order.integration_account:
                try:
                    store_cred = order.integration_account.credential
                except Exception:
                    pass

            # Determine marketplace type from provider
            marketplace = 'eldorado'
            if order.integration_account and order.integration_account.provider == 'gameboost':
                marketplace = 'gameboost'

            # Create batch + orders atomically
            from django.db import transaction
            with transaction.atomic():
                batch = RobuxCrateBatch.objects.create(
                    client_request_id=uuid_lib.uuid4(),
                    marketplace=marketplace,
                    marketplace_order_id=str(order.store_order_id),
                    marketplace_store=store_cred,
                    merchant=merchant,
                    roblox_username=username,
                    roblox_user_id=roblox_user_id,
                    place_id=str(place_candidates[0]['place_id']),
                    place_name=place_candidates[0].get('name', ''),
                    auto_place=True,
                    place_candidates=place_candidates,
                    place_attempt_index=0,
                    robux_amount=robux_amount,
                    quantity=1,
                )
                RobuxCrateOrder.objects.create(batch=batch)

            auto_order.batch = batch
            auto_order.state = 'order_created'
            auto_order.save(update_fields=['batch', 'state', 'updated_at'])

            logger.info(
                'robux_auto: created batch %s for order %s (username=%s, place=%s, robux=%s)',
                batch.id, order.store_order_id, username,
                place_candidates[0]['place_id'], robux_amount,
            )

            if bot_token and chat_id:
                _telegram_send(bot_token, chat_id,
                    f"\u2705 Robux Order Created Automatically\n\n"
                    f"Order   : {order.store_order_id}\n"
                    f"Username: {username}\n"
                    f"Place   : {place_candidates[0].get('name', 'Unknown')} (ID: {place_candidates[0]['place_id']})\n"
                    f"Amount  : {robux_amount:,} R$\n\n"
                    f"Delivery will complete automatically. No further action needed."
                )
            count += 1

        except Exception as exc:
            logger.error('robux_auto: failed to process order %s: %s', order.store_order_id, exc, exc_info=True)
            auto_order.error_message = str(exc)
            auto_order.state = 'failed'
            auto_order.save(update_fields=['error_message', 'state', 'updated_at'])

    return count


# ── Main APScheduler job ──────────────────────────────────────────────────────

def run_robux_auto_fulfillment_job() -> None:
    """Main APScheduler job — runs all three phases of auto-fulfillment."""
    try:
        new = detect_new_roblox_orders()
        replies = process_telegram_replies()
        created = process_username_received_orders()
        if new or replies or created:
            logger.info(
                'robux_auto: job complete — new=%d, replies=%d, orders_created=%d',
                new, replies, created,
            )
    except Exception as exc:
        logger.error('robux_auto: job failed: %s', exc, exc_info=True)
