"""
Eldorado negative-review monitor.

Polls /api/orders/me/reviews for each active Eldorado account and fires
Telegram notifications for newly seen negative reviews.

State strategy
--------------
Uses ``SyncCheckpoint(resource_type='reviews', mode='incremental')`` per
account.  The ``meta`` JSON field stores a ``seen_ids`` set — the IDs of
all negative reviews we have already processed.

Why seen-IDs instead of a watermark:
  Buyers can change their rating from Positive/Neutral → Negative *after*
  the original review date.  A date-based watermark misses these because
  the review keeps its original (old) date and appears below the watermark
  in the newest-first API response.  Tracking seen IDs catches every new
  appearance regardless of date ordering.

Poll logic:
  1. Fetch up to MAX_PAGES pages (newest → oldest) of negative reviews.
  2. Compare every review ID against ``seen_ids``.
  3. IDs not in ``seen_ids`` → new negative reviews → notify via Telegram.
  4. Replace ``seen_ids`` with the full set of IDs from the current fetch
     so that reviews whose rating changed back to positive are naturally
     pruned from the set.
  5. Bootstrap (empty ``seen_ids``): save all current IDs, do NOT notify.
"""

import logging
from typing import Any

from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import SyncCheckpoint
from apps.sync.services.eldorado.reviews.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

_PROVIDER = "eldorado"
_PAGE_SIZE = 7
_MAX_PAGES = 3
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

        accounts = list(
            IntegrationAccount.objects
            .select_related("credential")
            .filter(
                provider=_PROVIDER,
                is_active=True,
                credential__is_active=True,
            )
        )
        if not accounts:
            logger.debug("review_monitor: no active Eldorado accounts")
            return

        proxy_pool = build_proxy_pool()

        for account in accounts:
            try:
                self._check_account(account, proxy_pool)
            except Exception:
                logger.exception(
                    "review_monitor: unhandled error for account %s",
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

    def _check_account(
        self,
        account: IntegrationAccount,
        proxy_pool: Any,
    ) -> None:
        checkpoint, _ = SyncCheckpoint.objects.get_or_create(
            integration_account=account,
            resource_type=ResourceType.REVIEWS,
            mode=SyncMode.INCREMENTAL,
            defaults={"last_seen_remote_id": "", "cursor": ""},
        )

        facade = get_or_build_client(
            _PROVIDER,
            account.credential,
            proxy_pool=proxy_pool,
            proxy_group=get_group_name(account),
        )

        # Fetch up to _MAX_PAGES pages of negative reviews
        all_items = self._fetch_negative_reviews(facade, account.slug)
        if all_items is None:
            return  # API error — already logged

        current_ids = {item.orderReview.id for item in all_items}
        meta = checkpoint.meta or {}
        seen_ids = set(meta.get("seen_ids", []))

        # Bootstrap — first run, save all IDs, don't notify
        if not seen_ids and not checkpoint.last_seen_remote_id:
            meta["seen_ids"] = list(current_ids)
            checkpoint.meta = meta
            checkpoint.last_run_at = timezone.now()
            checkpoint.save(update_fields=["meta", "last_run_at", "updated_at"])
            logger.info(
                "review_monitor: bootstrap for %s — %d review(s) saved",
                account.slug, len(current_ids),
            )
            return

        # Migration: if old checkpoint has last_seen_remote_id but no seen_ids,
        # treat all current IDs as already seen to avoid a flood of notifications.
        if not seen_ids and checkpoint.last_seen_remote_id:
            seen_ids = current_ids.copy()
            logger.info(
                "review_monitor: migrated %s from watermark to seen_ids (%d ids)",
                account.slug, len(seen_ids),
            )

        # Find new reviews — IDs in current fetch that we haven't seen before
        new_ids = current_ids - seen_ids
        new_items = [
            item for item in all_items
            if item.orderReview.id in new_ids
        ]

        if not new_items:
            logger.debug("review_monitor: no new negative reviews for %s", account.slug)
        else:
            logger.info(
                "review_monitor: %d new negative review(s) for %s",
                len(new_items), account.slug,
            )
            for item in new_items:
                self._notifier.send_negative_review(
                    account_slug=account.slug,
                    review_item=item,
                )

        # Update seen_ids to current set (naturally prunes changed-back reviews)
        meta["seen_ids"] = list(current_ids)
        checkpoint.meta = meta
        checkpoint.last_run_at = timezone.now()
        checkpoint.save(update_fields=["meta", "last_run_at", "updated_at"])

    def _fetch_negative_reviews(self, facade: Any, account_slug: str) -> list | None:
        """Fetch up to _MAX_PAGES of negative reviews. Returns None on API error."""
        all_items: list = []
        cursor = _CURSOR_TOP

        for page_num in range(1, _MAX_PAGES + 1):
            result = facade.get_seller_reviews(
                params={
                    "cursorValue": cursor,
                    "pageDirection": "Next",
                    "pageSize": str(_PAGE_SIZE),
                    "feedbackRating": "Negative",
                },
            )

            if not result.ok:
                logger.error(
                    "review_monitor: reviews fetch failed for %s (page %d): %s",
                    account_slug, page_num, result.error,
                )
                # Return what we have so far if first page fails, abort entirely
                return None if page_num == 1 else all_items

            page = result.data.reviews
            if not page.results:
                break

            all_items.extend(page.results)

            if not page.nextPageCursor:
                break

            cursor = page.nextPageCursor

        return all_items
