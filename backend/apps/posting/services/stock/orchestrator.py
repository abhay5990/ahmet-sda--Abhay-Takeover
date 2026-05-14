"""Stock orchestrator — producer-consumer parallel processing per store.

Owns the job lifecycle:
- Resolves the job's source_account into a ``StockResolver`` (+ optional
  LZT image fetcher for media pipelines)
- Produces per-login prepare results and fans them out to per-store queues
- Spins up a ``StockConsumer`` thread per store (non-PA or PA variant)
- Finalises the job with accurate success/fail/skipped counts

Payload build and per-item processing live in sibling modules:
- ``stock.payload_builder`` — pure build_item_payload()
- ``stock.consumer`` — StockConsumer (consume_store, consume_store_pa)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from threading import Event

from django.db import DatabaseError, OperationalError

from apps.integrations.providers import registry
from apps.posting.models import (
    PostingDefault,
    PostingJob,
    PostingJobItem,
    PostingJobItemStatus,
    PostingJobStatus,
    PostingLog,
    PostingLogLevel,
)
from payload_pipeline.core.contracts import ListingKind

from apps.posting.resolvers.stock import StockResolver, DataMissing
from apps.posting.pipeline import adapter
from apps.posting.pipeline.templates import load_templates_for_posting
from apps.posting.services.shared.tracker_fetcher import fetch_tracker_data
from apps.posting.services.stock.consumer import StockConsumer
from apps.posting.services.stock.pa_bulk_uploader import PABulkUploader

logger = logging.getLogger(__name__)

# Sentinel value to signal store threads that production is done.
_SENTINEL = object()

# Backoff constants for 429 throttling.
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 30.0
_BACKOFF_FACTOR = 2.0
_MAX_RETRIES = 5  # Give up after 5 consecutive 429s


class StockOrchestrator:
    """Processes a stock PostingJob with store-based parallelism.

    Architecture: producer-consumer
    - Producer (main thread): iterates logins, runs prepare_once, pushes to store queues
    - Consumers (store threads): pull from queue, build marketplace payload, POST
    - PA consumers: accumulate rows, bulk upload every _PA_BATCH_SIZE items
    """

    def __init__(self):
        self._resolver: StockResolver | None = None
        self._image_fetcher = None  # ImageFetcher protocol instance
        self._imgur_downloader = None  # AlbumDownloader protocol instance
        self._cancel_event = Event()
        self._rate_limit_event = Event()
        self._pa_uploader = PABulkUploader()
        self._proxy_pool = None  # Built once at execute() start
        self._title_templates: dict[str, str] | None = None
        self._description_templates: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _build_resolver(self, source_account) -> StockResolver:
        """Build StockResolver, optionally with fallback from job's source_account."""
        if not source_account:
            return StockResolver()

        try:
            facade = registry.get_or_build_client(
                source_account.provider, source_account.credential,
            )
            self._build_image_fetcher(source_account)
            return StockResolver(
                lzt_facade=facade,
                lzt_account=source_account,
            )
        except (DatabaseError, OperationalError, AttributeError):
            logger.warning(
                "Could not build client for source account %s, fallback disabled",
                source_account,
            )
            return StockResolver()

    def _build_image_fetcher(self, source_account) -> None:
        """Build LztDefaultImageFetcher from source_account credentials."""
        try:
            from payload_pipeline.shared.lzt_default_fetcher import LztDefaultImageFetcher

            creds = source_account.credential.credentials or {}
            token = creds.get('api_key', '')
            if not token:
                logger.info("No LZT token — image fetcher disabled")
                return

            self._image_fetcher = LztDefaultImageFetcher(token=token)
            logger.debug("LZT image fetcher initialised")
        except (ImportError, AttributeError, KeyError) as exc:
            logger.warning("Could not build image fetcher: %s", exc)

    def _load_templates(self, game_id: int) -> None:
        """Load content templates from PostingDefault FK selections."""
        defaults = {
            d.marketplace: d
            for d in PostingDefault.objects.filter(
                game_id=game_id,
            ).select_related('title_template', 'description_template')
        }
        self._title_templates, self._description_templates = (
            load_templates_for_posting(game_id=game_id, posting_defaults=defaults)
        )
        if self._title_templates or self._description_templates:
            logger.info(
                "Content templates loaded: title=%s, description=%s",
                list(self._title_templates) if self._title_templates else None,
                list(self._description_templates) if self._description_templates else None,
            )

    def _build_imgur_downloader(self):
        """Build ImgurAlbumDownloader from active ServiceCredential."""

    def _build_consumer(self) -> StockConsumer:
        """Build the StockConsumer with shared collaborators."""
        return StockConsumer(
            cancel_event=self._cancel_event,
            rate_limit_event=self._rate_limit_event,
            pa_uploader=self._pa_uploader,
            post_with_backoff=self._post_with_backoff,
            is_cancelled=self._is_cancelled,
            sentinel=_SENTINEL,
            proxy_pool=self._proxy_pool,
        )

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    def execute(self, job_id: int) -> None:
        """Execute all pending items in a PostingJob using parallel store threads."""
        try:
            job = PostingJob.objects.select_related(
                'game', 'source_account',
            ).get(id=job_id)
        except PostingJob.DoesNotExist:
            logger.error("PostingJob %d not found", job_id)
            return

        # Build resolver from job's source_account
        self._resolver = self._build_resolver(job.source_account)

        # Clear stale clients so they get rebuilt with fresh proxy pool
        registry.clear_client_cache()

        # Build proxy pool once — ensures all clients use proxies
        from apps.integrations.proxy_pool import build_proxy_pool
        self._proxy_pool = build_proxy_pool()
        if self._proxy_pool:
            logger.info("Proxy pool ready: %d proxies", self._proxy_pool.size)

        # Build ImgurAlbumDownloader for manual media downloads
        self._imgur_downloader = self._build_imgur_downloader()

        # Load content templates from PostingDefault FK selections
        self._load_templates(job.game_id)

        job.status = PostingJobStatus.RUNNING
        job.save(update_fields=['status'])

        items = list(
            job.items.filter(
                status=PostingJobItemStatus.PENDING,
            ).select_related('owned_product', 'store', 'store__credential')
        )

        if not items:
            self._finalize_job(job)
            return

        # Group items by store_id → {store_id: [item, ...]}
        store_groups: dict[int, list[PostingJobItem]] = defaultdict(list)
        for item in items:
            store_groups[item.store_id].append(item)

        # Group items by login → {login: [item, ...]}
        # This lets the producer resolve once per login and push to store queues.
        login_items: dict[str, list[PostingJobItem]] = defaultdict(list)
        for item in items:
            login_items[item.login].append(item)

        # Create a queue per store
        store_queues: dict[int, Queue] = {
            store_id: Queue() for store_id in store_groups
        }

        consumer = self._build_consumer()

        # Launch consumer threads — one per store, PA gets a dedicated consumer
        with ThreadPoolExecutor(
            max_workers=len(store_groups),
            thread_name_prefix='store',
        ) as pool:
            futures: dict = {}
            for store_id in store_groups:
                first_item = store_groups[store_id][0]
                if first_item.marketplace == 'playerauctions':
                    store_slug = first_item.store.slug if first_item.store else ''
                    pa_mode = job.settings.get(store_slug, {}).get('pa_mode', 'bulk')
                    fn = consumer.consume_store if pa_mode == 'single' else consumer.consume_store_pa
                else:
                    fn = consumer.consume_store
                futures[pool.submit(fn, store_id, store_queues[store_id], job)] = store_id

            # Producer: prepare_once per unique login, push to store queues
            self._produce(login_items, store_queues, job)

            # Wait for all consumers to finish
            for future in as_completed(futures):
                crashed_store_id = futures[future]
                try:
                    future.result()
                except Exception:
                    logger.exception(
                        "Store thread crashed (store_id=%d, job=%d)",
                        crashed_store_id, job_id,
                    )
                    self._fail_remaining_items(
                        store_groups[crashed_store_id], job,
                        "Store thread crashed unexpectedly",
                    )

        self._finalize_job(job)

    # ------------------------------------------------------------------
    # Producer
    # ------------------------------------------------------------------

    def _produce(
        self,
        login_items: dict[str, list[PostingJobItem]],
        store_queues: dict[int, Queue],
        job: PostingJob,
    ) -> None:
        """Run prepare_once for each unique login and push to store queues."""
        for login, items in login_items.items():
            if self._is_cancelled(job):
                self._skip_items(items, "Job cancelled")
                continue

            # Resolve owned_product if not yet resolved
            first_item = items[0]
            if first_item.owned_product is None:
                self._resolve_items(items, job)
                # If still unresolved after fallback, items are already marked FAILED
                if first_item.owned_product is None:
                    continue

            prepared = self._prepare_once(login, first_item.owned_product, job)

            if not prepared['ok']:
                is_skip = prepared.get('error_category') == 'source_unsupported'
                status = PostingJobItemStatus.SKIPPED if is_skip else PostingJobItemStatus.FAILED
                log_level = PostingLogLevel.INFO if is_skip else PostingLogLevel.ERROR
                for item in items:
                    item.status = status
                    item.error_message = (
                        f"[{prepared['stage']}] {prepared['error']}"
                    )
                    item.save(update_fields=[
                        'status', 'error_message', 'updated_at',
                    ])
                    PostingLog.objects.create(
                        task_name='stock_post',
                        level=log_level,
                        message=f"prepare_once {'skipped' if is_skip else 'failed'}: {login}",
                        detail={
                            'item_id': item.id,
                            'job_id': job.id,
                            'stage': prepared['stage'],
                            'error': prepared['error'],
                            'error_category': prepared.get('error_category', ''),
                        },
                        integration_account=item.store,
                    )
                continue

            for item in items:
                store_id = item.store_id
                if store_id in store_queues:
                    store_queues[store_id].put((item, prepared['data']))

        for q in store_queues.values():
            q.put(_SENTINEL)

    def _resolve_items(
        self,
        items: list[PostingJobItem],
        job: PostingJob,
    ) -> None:
        """Resolve owned_product for items that have None — uses fallback."""
        login = items[0].login
        try:
            result = self._resolver.resolve(login, job.game)
            # Assign owned_product to all items with this login
            for item in items:
                item.owned_product = result.owned_product
                item.save(update_fields=['owned_product_id', 'updated_at'])
            logger.info("Resolved '%s' via fallback (job=%d)", login, job.id)
        except DataMissing as e:
            for item in items:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = f"[resolve] {e.reason}"
                item.save(update_fields=[
                    'status', 'error_message', 'updated_at',
                ])
            PostingLog.objects.create(
                task_name='stock_post',
                level=PostingLogLevel.WARNING,
                message=f"Resolve failed: {login}",
                detail={
                    'login': login,
                    'job_id': job.id,
                    'reason': e.reason,
                },
            )
        except Exception as e:
            logger.exception("Resolve failed for '%s'", login)
            for item in items:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = f"[resolve] {e}"
                item.save(update_fields=[
                    'status', 'error_message', 'updated_at',
                ])

    def _prepare_once(
        self,
        login: str,
        owned_product,
        job: PostingJob,
    ) -> dict:
        """Run the lib prepare phase with an already-resolved OwnedProduct.

        Returns standard pipeline format with 'prepared' (PreparedListing) instead
        of raw 'sources' — consumers use this to call adapter.build() per store.
        """
        try:
            # Build sources dict from owned_product
            raw = owned_product.raw_data
            if not raw:
                return {
                    'ok': False,
                    'stage': 'prepare_once',
                    'error': f"raw_data is empty for '{login}'",
                    'error_category': 'data_missing',
                }

            # Determine source key: manual entries use 'manual', otherwise provider
            if isinstance(raw, dict) and raw.get('source') == 'manual':
                source_key = 'manual'
            elif owned_product.source_account and owned_product.source_account.provider:
                source_key = owned_product.source_account.provider
            else:
                source_key = 'lzt'

            if source_key not in ('lzt', 'manual'):
                return {
                    'ok': False,
                    'stage': 'prepare_once',
                    'error': (
                        f"Source '{source_key}' is not supported for stock posting"
                        f" (login='{login}')."
                    ),
                    'error_category': 'source_unsupported',
                }

            sources: dict = {source_key: raw}
            tracker_data = fetch_tracker_data(job.game.slug, owned_product.raw_data)
            if tracker_data is not None:
                sources['tracker'] = tracker_data

            prepare_result = adapter.prepare(
                game_slug=job.game.slug,
                sources=sources,
                kind=ListingKind.STOCK,
                disable_media=False,
                lzt_image_fetcher=self._image_fetcher,
                imgur_album_downloader=self._imgur_downloader,
                title_templates=self._title_templates,
                description_templates=self._description_templates,
                ref_key=owned_product.ref_key or "",
            )
            if not prepare_result.success:
                return {
                    'ok': False,
                    'stage': prepare_result.error_stage or 'prepare_once',
                    'error': prepare_result.error or 'Pipeline prepare failed',
                    'error_category': 'pipeline_error',
                }
            return {
                'ok': True,
                'stage': 'prepare_once',
                'data': {
                    'owned_product': owned_product,
                    'prepared': prepare_result.prepared,
                },
            }
        except Exception as e:
            logger.exception("prepare_once failed for %s", login)
            return {
                'ok': False,
                'stage': 'prepare_once',
                'error': str(e),
                'error_category': 'unexpected',
            }

    # ------------------------------------------------------------------
    # Reactive throttling
    # ------------------------------------------------------------------

    def _post_with_backoff(self, item: PostingJobItem, payload: dict):
        """POST to marketplace with exponential backoff on 429.

        Gives up after _MAX_RETRIES consecutive rate limits or if the job is
        cancelled, returning the last failed result.
        """
        from apps.integrations.proxy_pool import get_group_name

        provider = registry.get_provider(item.marketplace)
        credential = item.store.credential
        proxy_group = get_group_name(item.store)

        facade = registry.get_or_build_client(
            item.marketplace, credential,
            proxy_pool=self._proxy_pool,
            proxy_group=proxy_group,
        )

        product_data = {'payload': payload}
        if proxy_group:
            product_data['proxy_group'] = proxy_group

        delay = _BACKOFF_BASE
        retries = 0
        while True:
            result = provider.create_listing(facade, product_data)

            if not result.ok:
                error = result.error
                logger.info(
                    "API error on %s (store=%s): status=%s category=%s message=%s details=%s",
                    item.marketplace, item.store.name,
                    result.status_code,
                    getattr(error, 'category', None),
                    getattr(error, 'message', None),
                    getattr(error, 'details', None),
                )

            if not result.ok and self._is_rate_limited(result):
                retries += 1
                if retries >= _MAX_RETRIES:
                    logger.error(
                        "Rate limit retry exhausted on %s (store=%s) after %d attempts — stopping job",
                        item.marketplace, item.store.name, retries,
                    )
                    self._rate_limit_event.set()
                    return result

                if self._cancel_event.is_set():
                    logger.info(
                        "Rate limit backoff aborted — job cancelled (store=%s)",
                        item.store.name,
                    )
                    return result

                logger.warning(
                    "Rate limited on %s (store=%s), backing off %.1fs (%d/%d)",
                    item.marketplace, item.store.name, delay, retries, _MAX_RETRIES,
                )
                # Use cancel_event.wait instead of time.sleep so cancel
                # interrupts the backoff immediately.
                self._cancel_event.wait(timeout=delay)
                delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_MAX)
                continue

            return result

    @staticmethod
    def _is_rate_limited(result) -> bool:
        """Check if API result indicates a 429 rate limit."""
        if not result.ok and result.error:
            error_msg = str(result.error.message).lower()
            error_cat = str(getattr(result.error, 'category', '')).lower()
            return (
                '429' in error_msg
                or 'rate limit' in error_msg
                or 'too many requests' in error_msg
                or error_cat == 'rate_limit'
            )
        return False

    # ------------------------------------------------------------------
    # Cancel support
    # ------------------------------------------------------------------

    def _is_cancelled(self, job: PostingJob) -> bool:
        """Check if the job has been cancelled (DB flag check)."""
        if self._cancel_event.is_set():
            return True
        job.refresh_from_db(fields=['status'])
        if job.status == PostingJobStatus.CANCELLED:
            self._cancel_event.set()
            return True
        return False

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _skip_items(
        self,
        items: list[PostingJobItem],
        reason: str,
    ) -> None:
        """Mark items as SKIPPED."""
        for item in items:
            if item.status == PostingJobItemStatus.PENDING:
                item.status = PostingJobItemStatus.SKIPPED
                item.error_message = reason
                item.save(update_fields=[
                    'status', 'error_message', 'updated_at',
                ])

    def _fail_remaining_items(
        self,
        items: list[PostingJobItem],
        job: PostingJob,
        reason: str,
    ) -> None:
        """Mark remaining PENDING/PROCESSING items as FAILED."""
        for item in items:
            if item.status in (
                PostingJobItemStatus.PENDING,
                PostingJobItemStatus.PROCESSING,
            ):
                item.status = PostingJobItemStatus.FAILED
                item.error_message = reason
                item.save(update_fields=[
                    'status', 'error_message', 'updated_at',
                ])
                PostingLog.objects.create(
                    task_name='stock_post',
                    level=PostingLogLevel.ERROR,
                    message=f"Thread crash: {item.login} → {item.store.name}",
                    detail={
                        'item_id': item.id,
                        'job_id': job.id,
                        'error': reason,
                    },
                    integration_account=item.store,
                )

    def _finalize_job(self, job: PostingJob) -> None:
        """Finalize job: count results, mark any orphan PENDING as FAILED, set status."""
        from django.utils import timezone

        orphan_count = job.items.filter(
            status__in=[PostingJobItemStatus.PENDING, PostingJobItemStatus.PROCESSING],
        ).update(
            status=PostingJobItemStatus.FAILED,
            error_message='Item was not processed (orphan)',
        )
        if orphan_count:
            logger.warning(
                "Job #%d: %d orphan PENDING items marked FAILED",
                job.id, orphan_count,
            )

        job.refresh_from_db(fields=['status'])
        was_cancelled = job.status == PostingJobStatus.CANCELLED

        job.success_count = job.items.filter(
            status=PostingJobItemStatus.SUCCESS,
        ).count()
        job.fail_count = job.items.filter(
            status=PostingJobItemStatus.FAILED,
        ).count()
        skipped_count = job.items.filter(
            status=PostingJobItemStatus.SKIPPED,
        ).count()

        if not was_cancelled:
            job.status = PostingJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=[
            'success_count', 'fail_count', 'status', 'completed_at',
        ])

        logger.info(
            "Job #%d %s: %d success, %d failed, %d skipped",
            job.id,
            'cancelled' if was_cancelled else 'completed',
            job.success_count,
            job.fail_count,
            skipped_count,
        )
