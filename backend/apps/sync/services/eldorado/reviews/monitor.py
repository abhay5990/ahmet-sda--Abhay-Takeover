"""
Eldorado negative-review monitor.

Polls /api/orders/me/reviews for each active Eldorado account and fires
Telegram notifications for newly seen negative reviews.

State strategy
--------------
Persists every seen review as an ``EldoradoReview`` row (one per
``account + remote_id``).  Row *existence* is the dedup key: a review we
already have a row for is never re-notified, even if it briefly drops out of
the API's paginated window or its rating is toggled.

This replaces the previous ``SyncCheckpoint.meta['seen_ids']`` approach,
which overwrote the seen set with only the current 21-item window on every
run — so reviews beyond that window were forgotten and re-notified whenever
they reappeared.

Poll logic:
  1. Fetch up to MAX_PAGES pages (newest → oldest) of negative reviews.
  2. Ingest: create a row for every review_id we don't already have.
       - Bootstrap (no rows yet for the account): seed silently
         (``notified=True``) so the first run never floods Telegram.
       - Otherwise new rows are created ``notified=False``.
  3. Dispatch: send a Telegram alert for every ``notified=False`` row, then
     mark it ``notified=True``.  ``notify_attempts`` bounds retries so a
     transient send failure is retried on the next run instead of lost.
"""

import logging
import re
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.sync.models import EldoradoReview
from apps.sync.services.eldorado.reviews.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

_PROVIDER = "eldorado"
_PAGE_SIZE = 7
_MAX_PAGES = 3
_CURSOR_TOP = "9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999"
# Cap retries so a review that can never be delivered (e.g. permanently bad
# payload) does not get re-attempted forever on every run.
_MAX_NOTIFY_ATTEMPTS = 5
# Eldorado timestamps carry up to 7 fractional-second digits; Python's parser
# only accepts 6, so trim the extras before parsing.
_FRACTIONAL_RE = re.compile(r"(\.\d{6})\d+")


def _parse_review_date(value: str | None):
    """Best-effort parse of an Eldorado ISO timestamp; returns None on failure."""
    if not value:
        return None
    try:
        return parse_datetime(_FRACTIONAL_RE.sub(r"\1", value))
    except (ValueError, TypeError):
        return None


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

        self._ingest(account, all_items)
        self._dispatch(account)

    def _ingest(self, account: IntegrationAccount, all_items: list) -> None:
        """Persist a row for every review we don't already have.

        On the very first run for an account (no rows yet) the fetched window is
        seeded silently — ``notified=True`` — so we don't flood Telegram with
        pre-existing reviews. Afterwards new rows are created ``notified=False``
        and left for :meth:`_dispatch` to deliver.
        """
        existing = set(
            EldoradoReview.objects
            .filter(integration_account=account)
            .values_list("remote_id", flat=True)
        )
        is_bootstrap = not existing
        now = timezone.now()

        created = 0
        for item in all_items:
            rid = item.orderReview.id
            if rid in existing:
                continue
            r = item.orderReview
            feedback = r.review
            EldoradoReview.objects.create(
                integration_account=account,
                remote_id=rid,
                feedback_rating=feedback.feedbackRating or "",
                game_category_title=r.gameCategoryTitle or "",
                review_message=(feedback.reviewMessage or "").strip(),
                feedback_tags=feedback.feedbackTags or [],
                was_initial_rating_positive=feedback.wasInitialRatingPositive,
                buyer_masked_username=item.buyer.maskedUsername or "",
                review_date=_parse_review_date(str(r.date) if r.date else None),
                raw=item.model_dump(mode="json"),
                notified=is_bootstrap,  # seeded rows are considered handled
                notified_at=now if is_bootstrap else None,
                first_seen_at=now,
            )
            existing.add(rid)
            created += 1

        if is_bootstrap:
            logger.info(
                "review_monitor: bootstrap for %s — %d review(s) seeded",
                account.slug, created,
            )
        elif created:
            logger.info(
                "review_monitor: %d new negative review(s) for %s",
                created, account.slug,
            )
        else:
            logger.debug("review_monitor: no new negative reviews for %s", account.slug)

    def _dispatch(self, account: IntegrationAccount) -> None:
        """Send a Telegram alert for every un-notified review (oldest first)."""
        pending = (
            EldoradoReview.objects
            .filter(
                integration_account=account,
                notified=False,
                notify_attempts__lt=_MAX_NOTIFY_ATTEMPTS,
            )
            .order_by("review_date")
        )
        for review in pending:
            sent = self._notifier.send_negative_review(
                account_slug=account.slug,
                review=review,
            )
            review.notify_attempts += 1
            if sent:
                review.notified = True
                review.notified_at = timezone.now()
            review.save(update_fields=[
                "notified", "notified_at", "notify_attempts", "updated_at",
            ])

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
