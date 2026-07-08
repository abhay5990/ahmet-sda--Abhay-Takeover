"""
Item Dropship Delivery Tracker — Telegram Bot for cross-team accountability.

Flow:
  1. Detect new GameBoost orders for dropshipped SAB items (DropshipProduct linked)
  2. Create DropshipDeliveryTracking record (state: PENDING_ELDORADO)
  3. Send Telegram notification with inline buttons to the combined team group
  4. Eldorado team taps "✅ Bought & Sent" → state → ELDORADO_DONE, log who/when
  5. GameBoost team taps "✅ GB Delivered" → state → FULLY_DELIVERED, log who/when
  6. Every 2 hours: remind about unactioned orders
  7. Handle callback_query updates from Telegram for button presses

Runs every 5 minutes via APScheduler.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

import django
import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("ITEM_DROPSHIP_BOT_TOKEN", "8986034916:AAFd1LoNS-GL3SEfcSK8q7UaBUL-EdGrXxA")
CHAT_ID = int(os.environ.get("ITEM_DROPSHIP_CHAT_ID", "-5542418551"))
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

REMINDER_HOURS = 2  # remind if not actioned within this many hours


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def _tg_post(method: str, payload: dict) -> dict:
    try:
        r = requests.post(f"{TG_API}/{method}", json=payload, timeout=15)
        return r.json()
    except Exception as exc:
        logger.error("Telegram %s failed: %s", method, exc)
        return {}


def _send_order_notification(tracking) -> int | None:
    """Send the initial order notification with inline buttons. Returns message_id."""
    order = tracking.order
    dp = tracking.dropship_product

    item_name = dp.product_title if dp else "Unknown Item"
    buy_price = float(dp.price) if dp and dp.price else 0.0
    sell_price = float(order.price)
    profit = sell_price - buy_price
    buyer = order.raw_data.get("buyerUsername") or order.raw_data.get("buyer_username") or "Unknown"
    gb_order_id = order.store_order_id

    text = (
        f"🛒 <b>New Item Dropship Order</b>\n\n"
        f"Item         : <b>{item_name}</b>\n"
        f"GameBoost ID : <code>{gb_order_id}</code>\n"
        f"Buyer        : {buyer}\n"
        f"Sell Price   : ${sell_price:.2f}\n"
        f"Buy Price    : ${buy_price:.2f}\n"
        f"Profit       : ${profit:.2f}\n\n"
        f"<b>Eldorado team:</b> Buy the item from Eldorado and tap ✅ below.\n"
        f"<b>GameBoost team:</b> Mark delivered on GameBoost and tap ✅ below."
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Eldorado: Bought & Sent",
                    "callback_data": f"eldo_done:{tracking.id}",
                },
                {
                    "text": "✅ GB: Marked Delivered",
                    "callback_data": f"gb_done:{tracking.id}",
                },
            ]
        ]
    }

    resp = _tg_post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    })

    result = resp.get("result", {})
    return result.get("message_id")


def _edit_message_buttons(message_id: int, tracking) -> None:
    """Update the inline keyboard to reflect current state."""
    from apps.tools.models import DropshipDeliveryTracking

    eldo_done = tracking.state in (
        DropshipDeliveryTracking.State.ELDORADO_DONE,
        DropshipDeliveryTracking.State.FULLY_DELIVERED,
    )
    gb_done = tracking.state == DropshipDeliveryTracking.State.FULLY_DELIVERED

    eldo_label = f"✅ Eldorado: {tracking.eldorado_done_by} ✓" if eldo_done else "✅ Eldorado: Bought & Sent"
    gb_label = f"✅ GB: {tracking.gb_done_by} ✓" if gb_done else "✅ GB: Marked Delivered"

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": eldo_label,
                    "callback_data": f"eldo_done:{tracking.id}" if not eldo_done else "noop",
                },
                {
                    "text": gb_label,
                    "callback_data": f"gb_done:{tracking.id}" if not gb_done else "noop",
                },
            ]
        ]
    }

    _tg_post("editMessageReplyMarkup", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "reply_markup": keyboard,
    })


def _send_completion_message(tracking) -> None:
    """Send a completion summary when both steps are done."""
    order = tracking.order
    dp = tracking.dropship_product
    item_name = dp.product_title if dp else "Unknown Item"

    text = (
        f"✅ <b>Order Fully Delivered</b>\n\n"
        f"Item         : <b>{item_name}</b>\n"
        f"GameBoost ID : <code>{order.store_order_id}</code>\n\n"
        f"Eldorado step: {tracking.eldorado_done_by} @ "
        f"{tracking.eldorado_done_at.strftime('%H:%M %d/%m') if tracking.eldorado_done_at else 'N/A'}\n"
        f"GB step      : {tracking.gb_done_by} @ "
        f"{tracking.gb_done_at.strftime('%H:%M %d/%m') if tracking.gb_done_at else 'N/A'}"
    )

    _tg_post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })


def _send_reminder(tracking) -> None:
    """Send a reminder for orders that haven't been actioned."""
    from apps.tools.models import DropshipDeliveryTracking

    order = tracking.order
    dp = tracking.dropship_product
    item_name = dp.product_title if dp else "Unknown Item"

    if tracking.state == DropshipDeliveryTracking.State.PENDING_ELDORADO:
        pending_step = "⏳ Waiting for Eldorado team to buy & send"
    else:
        pending_step = "⏳ Waiting for GameBoost team to mark delivered"

    text = (
        f"⚠️ <b>Order Reminder — Action Required</b>\n\n"
        f"Item         : <b>{item_name}</b>\n"
        f"GameBoost ID : <code>{order.store_order_id}</code>\n"
        f"Status       : {pending_step}\n\n"
        f"Please action this order ASAP."
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Eldorado: Bought & Sent",
                    "callback_data": f"eldo_done:{tracking.id}",
                },
                {
                    "text": "✅ GB: Marked Delivered",
                    "callback_data": f"gb_done:{tracking.id}",
                },
            ]
        ]
    }

    _tg_post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    })


# ---------------------------------------------------------------------------
# Callback query handler
# ---------------------------------------------------------------------------

def _process_callback_updates() -> None:
    """Poll Telegram for callback_query updates (button presses) and process them."""
    from apps.tools.models import DropshipDeliveryTracking

    # Get updates with offset to avoid reprocessing
    # We use a simple approach: fetch recent updates and process unhandled ones
    resp = _tg_post("getUpdates", {
        "timeout": 0,
        "allowed_updates": ["callback_query"],
        "limit": 100,
    })

    updates = resp.get("result", [])
    if not updates:
        return

    last_update_id = None

    for update in updates:
        last_update_id = update.get("update_id")
        cq = update.get("callback_query")
        if not cq:
            continue

        data = cq.get("data", "")
        callback_id = cq.get("id")
        user = cq.get("from", {})
        username = user.get("username") or user.get("first_name") or f"User#{user.get('id')}"

        # Acknowledge the callback immediately
        _tg_post("answerCallbackQuery", {
            "callback_query_id": callback_id,
            "text": "Recorded ✅",
        })

        if data == "noop":
            continue

        if data.startswith("eldo_done:") or data.startswith("gb_done:"):
            try:
                tracking_id = int(data.split(":")[1])
                tracking = DropshipDeliveryTracking.objects.select_related(
                    "order", "dropship_product"
                ).get(id=tracking_id)
            except (DropshipDeliveryTracking.DoesNotExist, ValueError):
                continue

            now = timezone.now()

            if data.startswith("eldo_done:"):
                if tracking.state == DropshipDeliveryTracking.State.PENDING_ELDORADO:
                    tracking.state = DropshipDeliveryTracking.State.ELDORADO_DONE
                    tracking.eldorado_done_by = username
                    tracking.eldorado_done_at = now
                    tracking.save(update_fields=["state", "eldorado_done_by", "eldorado_done_at", "updated_at"])
                    logger.info("Tracking #%d: Eldorado step done by %s", tracking_id, username)

                    # Update button labels
                    if tracking.telegram_message_id:
                        _edit_message_buttons(tracking.telegram_message_id, tracking)

            elif data.startswith("gb_done:"):
                if tracking.state in (
                    DropshipDeliveryTracking.State.PENDING_ELDORADO,
                    DropshipDeliveryTracking.State.ELDORADO_DONE,
                ):
                    # If Eldorado step wasn't done yet, mark it too (GB team confirms both)
                    if not tracking.eldorado_done_at:
                        tracking.eldorado_done_by = f"{username} (via GB)"
                        tracking.eldorado_done_at = now

                    tracking.state = DropshipDeliveryTracking.State.FULLY_DELIVERED
                    tracking.gb_done_by = username
                    tracking.gb_done_at = now
                    tracking.save(update_fields=[
                        "state", "eldorado_done_by", "eldorado_done_at",
                        "gb_done_by", "gb_done_at", "updated_at"
                    ])
                    logger.info("Tracking #%d: GB step done by %s — FULLY DELIVERED", tracking_id, username)

                    # Update button labels
                    if tracking.telegram_message_id:
                        _edit_message_buttons(tracking.telegram_message_id, tracking)

                    # Send completion summary
                    _send_completion_message(tracking)

    # Advance the offset so we don't reprocess these updates next time
    if last_update_id is not None:
        _tg_post("getUpdates", {
            "offset": last_update_id + 1,
            "limit": 1,
            "timeout": 0,
        })


# ---------------------------------------------------------------------------
# Main scheduler job
# ---------------------------------------------------------------------------

def run_item_dropship_delivery_tracker() -> None:
    """Main entry point — called every 5 minutes by APScheduler."""
    try:
        _process_callback_updates()
        _detect_new_orders()
        _send_reminders()
    except Exception as exc:
        logger.exception("item_dropship_delivery_tracker error: %s", exc)


def _detect_new_orders() -> None:
    """Find new GameBoost orders for dropshipped items and create tracking records."""
    from apps.tools.models import DropshipDeliveryTracking
    from apps.orders.models import Order
    from apps.orders.enums import OrderStatus
    # Find GameBoost orders for dropshipped items that don't have a tracking record yet
    gameboost_orders = (
        Order.objects
        .filter(
            integration_account__provider="gameboost",
            dropship_product__isnull=False,
            status__in=[OrderStatus.PENDING, OrderStatus.DELIVERED],
        )
        .exclude(
            id__in=DropshipDeliveryTracking.objects.values_list("order_id", flat=True)
        )
        .select_related("dropship_product", "game", "integration_account")
        .order_by("created_at")
    )

    for order in gameboost_orders:
        tracking = DropshipDeliveryTracking.objects.create(
            order=order,
            dropship_product=order.dropship_product,
            state=DropshipDeliveryTracking.State.PENDING_ELDORADO,
        )

        # Send Telegram notification
        message_id = _send_order_notification(tracking)
        if message_id:
            tracking.telegram_message_id = message_id
            tracking.notified_at = timezone.now()
            tracking.save(update_fields=["telegram_message_id", "notified_at"])

        logger.info(
            "New dropship order tracked: #%d (order %s, item: %s)",
            tracking.id,
            order.store_order_id,
            order.dropship_product.product_title if order.dropship_product else "?",
        )


def _send_reminders() -> None:
    """Send reminders for orders that haven't been actioned within REMINDER_HOURS."""
    from apps.tools.models import DropshipDeliveryTracking

    cutoff = timezone.now() - timedelta(hours=REMINDER_HOURS)

    pending = DropshipDeliveryTracking.objects.filter(
        state__in=[
            DropshipDeliveryTracking.State.PENDING_ELDORADO,
            DropshipDeliveryTracking.State.ELDORADO_DONE,
        ],
        notified_at__lt=cutoff,
        last_reminded_at__isnull=True,  # only remind once (or extend logic for multiple)
    ).select_related("order", "dropship_product")

    for tracking in pending:
        _send_reminder(tracking)
        tracking.last_reminded_at = timezone.now()
        tracking.save(update_fields=["last_reminded_at"])
        logger.info("Reminder sent for tracking #%d", tracking.id)
