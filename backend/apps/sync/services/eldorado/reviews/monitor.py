"""
Eldorado negative-review monitor.

Polls /api/orders/me/reviews for each active Eldorado account and fires
Telegram notifications for newly seen negative reviews.

State strategy
--------------
Uses ``SyncCheckpoint(resource_type='reviews', mode='incremental')`` per
account.  The ``last_seen_remote_id`` field stores the review ID of the most
recently seen review (newest-first ordering).

Why NOT cursor-based:
  The API cursor goes *backward* in time (pageDirection=Next → older reviews).
  There is no reliable way to reconstruct a "forward" cursor without the
  opaque value from the API response.  Storing last_seen_remote_id and always
  fetching the first page (newest) is simpler and correct.

Poll logic:
  1. Fetch first page (newest → oldest) with sentinel cursor.
  2. Collect every result that appears BEFORE last_seen_remote_id in the list.
     These are reviews newer than what we last saw.
  3. Bootstrap (no stored ID): save first result's ID, do NOT notify.
  4. Normal run: notify new reviews, update last_seen_remote_id to the
     first (most recent) result's ID.

Edge case: if more than PAGE_SIZE new reviews arrive between polls, the
extras are missed until the next run.  At a 10-min interval this is
acceptable; escalation to multi-page sweep can be added later.
"""

import logging

from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import SyncCheckpoint
from apps.sync.services.eldorado.reviews.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

_PROVIDER = "eldorado"
_PAGE_SIZE = 20
_CURSOR_TOP = "9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999"


class EldoradoReviewMonitor:
    """Checks all active Eldorado accounts for new negative reviews."""

    def __init__(self, notifier: TelegramNotifier | None = None) -> None:
        self._notifier = notifier or TelegramNotifier()

    def check_all_accounts(self, *, first_run: bool = False) -> None:
        """Entry point — iterates over every active Eldorado account.

        Args:
            first_run: If True, sends a startup notification to Telegram.
        """
        if first_run:
            self._send_startup_message()

        accounts = (
            IntegrationAccount.objects
            .select_related("credential")
            .filter(provider=_PROVIDER, is_active=True)
        )
        for account in accounts:
            try:
                self._check_account(account)
            except Exception:
                logger.exception(
                    "Unexpected error in review monitor for account %s",
                    account.slug,
                )

    def _send_startup_message(self) -> None:
        """Send a Telegram message indicating the review monitor has started."""
        from apps.sync.services.eldorado.reviews.notifier import _get_telegram_client

        client, chat_id = _get_telegram_client()
        if client is None or not chat_id:
            logger.warning("Telegram not configured — skipping startup message")
            return

        text = (
            "✅ Review Monitor Started\n"
            "Eldorado negative review monitoring is now active.\n"
            "You will receive alerts for any new negative reviews."
        )
        result = client.send_message(chat_id=chat_id, text=text)
        if result.ok:
            logger.info("Review monitor startup message sent to Telegram")
        else:
            logger.error("Failed to send startup message: %s", result.error)

    def _check_account(self, account: IntegrationAccount) -> None:
        checkpoint, _ = SyncCheckpoint.objects.get_or_create(
            integration_account=account,
            resource_type=ResourceType.REVIEWS,
            mode=SyncMode.INCREMENTAL,
            defaults={"last_seen_remote_id": "", "cursor": ""},
        )

        facade = get_or_build_client(_PROVIDER, account.credential)
        result = facade.get_seller_reviews(
            params={
                "cursorValue": _CURSOR_TOP,
                "pageDirection": "Next",
                "pageSize": str(_PAGE_SIZE),
                "feedbackRating": "Negative",
            },
        )

        if not result.ok:
            logger.error(
                "Reviews fetch failed for %s: %s", account.slug, result.error
            )
            return

        results = result.data.reviews.results
        if not results:
            logger.debug("No negative reviews found for %s", account.slug)
            return

        last_seen_id = checkpoint.last_seen_remote_id
        last_seen_date = (checkpoint.meta or {}).get("last_seen_date", "")
        most_recent = results[0].orderReview

        # Bootstrap — first run, just save the watermark, don't notify
        if not last_seen_id:
            checkpoint.last_seen_remote_id = most_recent.id
            checkpoint.meta = {**(checkpoint.meta or {}), "last_seen_date": most_recent.date}
            checkpoint.last_run_at = timezone.now()
            checkpoint.save(update_fields=["last_seen_remote_id", "meta", "last_run_at", "updated_at"])
            logger.info(
                "Review monitor bootstrap for %s — watermark set to %s (%d reviews on page)",
                account.slug, most_recent.id, len(results),
            )
            return

        # Collect reviews newer than last_seen_id (they appear before it in the list)
        new_reviews = []
        found_watermark = False
        for item in results:
            if item.orderReview.id == last_seen_id:
                found_watermark = True
                break
            new_reviews.append(item)

        if not found_watermark:
            # Watermark review is no longer in the Negative list — the buyer likely
            # changed their rating from Negative to Neutral/Positive, or an admin
            # removed it. Fall back to date comparison to avoid sending 20 notifications.
            if last_seen_date:
                new_reviews = [
                    item for item in results
                    if item.orderReview.date > last_seen_date
                ]
                logger.warning(
                    "Watermark review %s not found for %s (rating probably changed) "
                    "— date fallback: %d new review(s)",
                    last_seen_id, account.slug, len(new_reviews),
                )
            else:
                logger.warning(
                    "Watermark review %s not found for %s, no date fallback — skipping "
                    "to avoid duplicate notifications",
                    last_seen_id, account.slug,
                )
                new_reviews = []

        if not new_reviews:
            logger.debug("No new negative reviews for %s", account.slug)
        else:
            logger.info("%d new negative review(s) for %s", len(new_reviews), account.slug)
            for item in new_reviews:
                self._notifier.send_negative_review(
                    account_slug=account.slug,
                    review_item=item,
                )

        # Advance watermark to the most recent review on this page
        checkpoint.last_seen_remote_id = most_recent.id
        checkpoint.meta = {**(checkpoint.meta or {}), "last_seen_date": most_recent.date}
        checkpoint.last_run_at = timezone.now()
        checkpoint.save(update_fields=["last_seen_remote_id", "meta", "last_run_at", "updated_at"])
