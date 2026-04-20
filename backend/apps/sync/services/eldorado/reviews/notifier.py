"""
Telegram notifier for Eldorado review alerts.

Reads bot token and chat ID from the active ServiceCredential with
service_type='notification'. Falls back gracefully if not configured.
"""

import logging

from apis_sdk.clients.marketplaces.eldorado.models import EldoradoReviewItem

logger = logging.getLogger(__name__)


def _get_telegram_client():
    """Return (TelegramClient, chat_id) from the active notification credential.

    Returns (None, None) if not configured or no active credential exists.
    """
    try:
        from apps.integrations.models import ServiceCredential
        from apps.integrations.services.registry import get_service

        credential = (
            ServiceCredential.objects
            .filter(service_type='notification', is_active=True)
            .first()
        )
        if not credential:
            return None, None

        service = get_service('notification')
        if service is None:
            return None, None

        client = service.build_client(credential)
        chat_id = (credential.credentials or {}).get('chat_id', '')
        return client, chat_id
    except Exception as exc:
        logger.error("Failed to build Telegram client: %s", exc)
        return None, None


class TelegramNotifier:
    """Sends Telegram notifications via the active notification ServiceCredential."""

    def send_negative_review(
        self,
        *,
        account_slug: str,
        review_item: EldoradoReviewItem,
    ) -> None:
        """Send a formatted negative review notification to Telegram."""
        client, chat_id = _get_telegram_client()
        if client is None or not chat_id:
            logger.warning(
                "Telegram not configured (no active notification ServiceCredential) "
                "— skipping review notification"
            )
            return

        r = review_item.orderReview
        feedback = r.review
        tags = ", ".join(feedback.feedbackTags) if feedback.feedbackTags else "—"
        comment = feedback.reviewMessage.strip() or "—"
        buyer = review_item.buyer.maskedUsername or "unknown"

        text = (
            "⚠️ New Negative Review — Eldorado\n"
            f"Account : {account_slug}\n"
            f"Buyer   : {buyer}\n"
            f"Category: {r.gameCategoryTitle}\n"
            f"Tags    : {tags}\n"
            f"Comment : {comment}\n"
            f"Date    : {r.date}"
        )

        result = client.send_message(chat_id=chat_id, text=text)
        if not result.ok:
            logger.error("Telegram send failed: %s", result.error)
