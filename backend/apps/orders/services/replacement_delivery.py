"""Verified post-commit replacement delivery helpers.

Only GameBoost has a configured, direct customer-message primitive.  Other
marketplaces deliberately remain manual handoffs until a verified route exists.
Credential text is returned to the staff UI but is never persisted in delivery
logs or provider-error fields.
"""
from __future__ import annotations

import logging

from apps.integrations.providers.registry import get_or_build_client
from apps.orders.models import ReplacementDeliveryStatus

logger = logging.getLogger(__name__)


def _message_for(product) -> str:
    lines = [
        "Hello, a replacement account has been assigned for your order.",
        "",
        f"Login: {product.login}",
        f"Password: {product.password}",
    ]
    if product.email:
        lines.append(f"Email: {product.email}")
    if product.email_password:
        lines.append(f"Email Password: {product.email_password}")
    lines.extend(["", "Please confirm once you can access the replacement account."])
    return "\n".join(lines)


def deliver_replacement(order, replacement) -> dict:
    """Send one non-retried GameBoost message after an already committed swap.

    Returns a staff-safe status payload.  A failure only records the exact
    provider error and never rolls back the committed stock replacement.
    """
    account = order.integration_account
    if not account or account.provider != 'gameboost':
        replacement.delivery_status = ReplacementDeliveryStatus.MANUAL
        replacement.delivery_channel = 'manual_handoff'
        replacement.delivery_error = ''
        replacement.save(update_fields=[
            'delivery_status', 'delivery_channel', 'delivery_error',
        ])
        return {
            'status': ReplacementDeliveryStatus.MANUAL,
            'channel': 'manual_handoff',
            'message': 'Manual customer handoff required for this marketplace.',
        }

    credential = getattr(account, 'credential', None)
    if not credential or not credential.is_active or not order.store_order_id:
        detail = 'GameBoost customer message could not be sent: active store credentials or order ID are missing.'
        replacement.delivery_status = ReplacementDeliveryStatus.FAILED
        replacement.delivery_channel = 'gameboost_chat'
        replacement.delivery_error = detail
        replacement.save(update_fields=[
            'delivery_status', 'delivery_channel', 'delivery_error',
        ])
        return {
            'status': ReplacementDeliveryStatus.FAILED,
            'channel': 'gameboost_chat',
            'message': detail,
        }

    try:
        client = get_or_build_client('gameboost', credential)
        result = client.send_order_message(
            str(order.store_order_id), _message_for(replacement.new_product),
        )
    except Exception:  # no credential data or message content is logged
        logger.exception('GameBoost replacement message raised for order=%s', order.pk)
        result = None

    if result is not None and result.ok:
        provider_message_id = str(getattr(result.data, 'id', '') or '')
        replacement.delivery_status = ReplacementDeliveryStatus.SENT
        replacement.delivery_channel = 'gameboost_chat'
        replacement.delivery_message_id = provider_message_id
        replacement.delivery_error = ''
        replacement.save(update_fields=[
            'delivery_status', 'delivery_channel', 'delivery_message_id',
            'delivery_error',
        ])
        return {
            'status': ReplacementDeliveryStatus.SENT,
            'channel': 'gameboost_chat',
            'message': 'GameBoost customer message sent and confirmed by the provider.',
        }

    error_message = (
        getattr(getattr(result, 'error', None), 'message', None)
        if result is not None else None
    ) or 'GameBoost customer message failed before provider confirmation.'
    replacement.delivery_status = ReplacementDeliveryStatus.FAILED
    replacement.delivery_channel = 'gameboost_chat'
    replacement.delivery_error = str(error_message)[:2000]
    replacement.save(update_fields=[
        'delivery_status', 'delivery_channel', 'delivery_error',
    ])
    return {
        'status': ReplacementDeliveryStatus.FAILED,
        'channel': 'gameboost_chat',
        'message': str(error_message),
    }
