"""Per-store consumer worker — extracted from StockOrchestrator.

Hosts the two consumer flavours driven by a ``queue.Queue``:

- ``consume_store``    : non-PA marketplaces (one-by-one POST)
- ``consume_store_pa`` : PlayerAuctions (accumulate → bulk upload)

Shared collaborators (``cancel_event``, ``pa_uploader``, ``post_with_backoff``,
``is_cancelled``) are passed explicitly at construction — the consumer does
not need a reference back to the orchestrator.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from queue import Queue
from threading import Event
from typing import Callable

from django.db import close_old_connections

from apps.integrations.providers import registry
from apps.integrations.proxy_pool import get_group_name
from apps.posting.models import (
    PostingJob,
    PostingJobItem,
    PostingJobItemStatus,
    PostingLog,
    PostingLogLevel,
)
from apps.posting.services.shared import persist_success
from apps.posting.services.shared.utils import extract_listing_id
from apps.posting.services.stock.pa_bulk_uploader import PABulkUploader, PABatchResult
from apps.posting.services.stock.payload_builder import build_item_payload

logger = logging.getLogger(__name__)

# PA batch size — flush the accumulator once it reaches this count.
_PA_BATCH_SIZE = 10


class StockConsumer:
    """Thread-safe single-store queue consumer.

    One ``StockConsumer`` instance is shared across all store-threads; thread
    safety comes from the fact that each method only touches local variables
    and the per-store ``Queue``.
    """

    def __init__(
        self,
        *,
        cancel_event: Event,
        pa_uploader: PABulkUploader,
        post_with_backoff: Callable[[PostingJobItem, dict], object],
        is_cancelled: Callable[[PostingJob], bool],
        sentinel: object,
        proxy_pool=None,
    ):
        self._cancel_event = cancel_event
        self._pa_uploader = pa_uploader
        self._post_with_backoff = post_with_backoff
        self._is_cancelled = is_cancelled
        self._sentinel = sentinel
        self._proxy_pool = proxy_pool

    # ------------------------------------------------------------------
    # Non-PA consumer
    # ------------------------------------------------------------------

    def consume_store(
        self,
        store_id: int,
        queue: Queue,
        job: PostingJob,
    ) -> None:
        """Consumer thread: pull items from queue, build + POST one by one."""
        try:
            close_old_connections()

            while True:
                entry = queue.get()
                if entry is self._sentinel:
                    break

                item, prepared_data = entry

                if self._is_cancelled(job):
                    item.status = PostingJobItemStatus.SKIPPED
                    item.error_message = 'Job cancelled'
                    item.save(update_fields=[
                        'status', 'error_message', 'updated_at',
                    ])
                    continue

                self._process_item(item, prepared_data, job)

        finally:
            close_old_connections()

    def _process_item(
        self,
        item: PostingJobItem,
        prepared_data: dict,
        job: PostingJob,
    ) -> None:
        """Process a single non-PA item: build payload → POST → create Listing."""
        item.status = PostingJobItemStatus.PROCESSING
        item.save(update_fields=['status', 'updated_at'])

        try:
            build_result = build_item_payload(item, prepared_data, job)

            if not build_result['ok']:
                raise ValueError(
                    f"[{build_result['stage']}] {build_result['error']}"
                )

            payload = build_result['data']['payload']
            final_price: Decimal = build_result['data']['final_price']
            sub_platform: str = build_result['data']['sub_platform']
            owned_product = prepared_data['owned_product']

            api_result = self._post_with_backoff(item, payload)

            if not api_result.ok:
                raise RuntimeError(
                    f"API error: {api_result.error.message}"
                    f" (category={api_result.error.category})"
                )

            store_listing_id = extract_listing_id(api_result.data)

            persist_success(
                item=item,
                job=job,
                owned_product=owned_product,
                store_listing_id=store_listing_id,
                sub_platform=sub_platform,
                final_price=final_price,
                payload=payload,
                response_data=api_result.data,
            )

        except Exception as e:
            item.status = PostingJobItemStatus.FAILED
            item.error_message = str(e)
            logger.exception("Item #%d failed: %s", item.id, e)

            PostingLog.objects.create(
                task_name='stock_post',
                level=PostingLogLevel.ERROR,
                message=f"Post failed: {item.login} → {item.store.name}",
                detail={
                    'item_id': item.id,
                    'job_id': job.id,
                    'stage': f'build_{item.marketplace}',
                    'error': str(e),
                },
                integration_account=item.store,
            )

        item.save(update_fields=['status', 'error_message', 'listing', 'updated_at'])

    # ------------------------------------------------------------------
    # PA consumer (bulk upload)
    # ------------------------------------------------------------------

    def consume_store_pa(
        self,
        store_id: int,
        queue: Queue,
        job: PostingJob,
    ) -> None:
        """PA consumer: accumulate items, bulk upload every _PA_BATCH_SIZE.

        Each entry in the accumulator:
            (item, prepared_data, excel_row_dict, build_data_dict)
        """
        try:
            close_old_connections()

            facade = None
            proxy_group: str | None = None
            accumulator: list[tuple] = []

            while True:
                entry = queue.get()
                if entry is self._sentinel:
                    break

                item, prepared_data = entry

                if self._is_cancelled(job):
                    item.status = PostingJobItemStatus.SKIPPED
                    item.error_message = 'Job cancelled'
                    item.save(update_fields=[
                        'status', 'error_message', 'updated_at',
                    ])
                    continue

                # Build facade lazily from first item
                if facade is None:
                    proxy_group = get_group_name(item.store)
                    facade = registry.get_or_build_client(
                        item.marketplace, item.store.credential,
                        proxy_pool=self._proxy_pool,
                        proxy_group=proxy_group,
                    )

                build_result = build_item_payload(item, prepared_data, job)

                if not build_result['ok']:
                    item.status = PostingJobItemStatus.FAILED
                    item.error_message = (
                        f"[{build_result['stage']}] {build_result['error']}"
                    )
                    item.save(update_fields=[
                        'status', 'error_message', 'updated_at',
                    ])
                    PostingLog.objects.create(
                        task_name='stock_post',
                        level=PostingLogLevel.ERROR,
                        message=f"PA build failed: {item.login}",
                        detail={
                            'item_id': item.id,
                            'job_id': job.id,
                            'stage': build_result['stage'],
                            'error': build_result['error'],
                            'error_category': build_result.get('error_category', ''),
                        },
                        integration_account=item.store,
                    )
                    continue

                excel_row = build_result['data']['payload']
                build_data = build_result['data']
                accumulator.append((item, prepared_data, excel_row, build_data))

                if len(accumulator) >= _PA_BATCH_SIZE:
                    self._flush_pa_batch(accumulator, facade, job, proxy_group)
                    accumulator.clear()

            # Flush remaining < _PA_BATCH_SIZE
            if accumulator and facade is not None:
                self._flush_pa_batch(accumulator, facade, job, proxy_group)

        finally:
            close_old_connections()

    def _flush_pa_batch(
        self,
        batch: list[tuple],
        facade,
        job: PostingJob,
        proxy_group: str | None,
    ) -> None:
        """Upload a PA batch and create Listings for successful items."""
        items = [b[0] for b in batch]
        prepared_data_list = [b[1] for b in batch]
        excel_rows = [b[2] for b in batch]
        build_data_list = [b[3] for b in batch]

        for item in items:
            item.status = PostingJobItemStatus.PROCESSING
            item.save(update_fields=['status', 'updated_at'])

        logger.info("PA flush: %d rows (job=%d)", len(excel_rows), job.id)

        batch_result: PABatchResult = self._pa_uploader.upload_batch(
            facade, excel_rows, proxy_group=proxy_group,
        )

        for idx, item in enumerate(items):
            if idx in batch_result.successful:
                offer_id = batch_result.successful[idx]
                final_price: Decimal = build_data_list[idx]['final_price']
                sub_platform: str = build_data_list[idx]['sub_platform']
                owned_product = prepared_data_list[idx]['owned_product']

                try:
                    persist_success(
                        item=item,
                        job=job,
                        owned_product=owned_product,
                        store_listing_id=offer_id,
                        sub_platform=sub_platform,
                        final_price=final_price,
                        payload=excel_rows[idx],
                        response_data={'offer_id': offer_id},
                    )
                except Exception as exc:
                    item.status = PostingJobItemStatus.FAILED
                    item.error_message = f'Listing creation failed: {exc}'
                    logger.exception("PA listing create failed for item #%d", item.id)
            else:
                error_msg = batch_result.failed.get(idx, 'PA upload failed')
                item.status = PostingJobItemStatus.FAILED
                item.error_message = error_msg
                PostingLog.objects.create(
                    task_name='stock_post',
                    level=PostingLogLevel.ERROR,
                    message=f"PA upload failed: {item.login}",
                    detail={
                        'item_id': item.id,
                        'job_id': job.id,
                        'stage': 'build_playerauctions',
                        'error': error_msg,
                    },
                    integration_account=item.store,
                )

            item.save(update_fields=['status', 'error_message', 'listing', 'updated_at'])
