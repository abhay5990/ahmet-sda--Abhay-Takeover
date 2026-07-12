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
from apps.posting.services.shared.listing_writer import (
    add_failed_owned_products_to_pool,
    persist_multi_cred_success,
)
from apps.posting.services.shared.max_offer_error import is_max_offer_error
from apps.posting.services.shared.utils import extract_listing_id
from apps.posting.services.variant_context import build_variant_context
from apps.posting.services.variant_routing import PLATFORM_PRIORITY, VariantRouter
from apps.posting.services.stock.pa_bulk_uploader import PABulkUploader, PABatchResult
from apps.posting.services.stock.pa_relay_poster import PARelayPoster, PARelayPostResult, fetch_relay_token
from apps.posting.services.stock.payload_builder import build_item_payload
from core.marketplace.normalizers import normalize_offer_response

logger = logging.getLogger(__name__)

# PA batch size — flush the accumulator once it reaches this count.
_PA_BATCH_SIZE = 10
_MULTI_CRED_MARKETPLACES: frozenset[str] = frozenset({'eldorado', 'gameboost'})


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
        rate_limit_event: Event,
        pa_uploader: PABulkUploader,
        post_with_backoff: Callable[[PostingJobItem, dict], object],
        is_cancelled: Callable[[PostingJob], bool],
        sentinel: object,
        proxy_pool=None,
    ):
        self._cancel_event = cancel_event
        self._rate_limit_event = rate_limit_event
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
        """Consumer thread: pull items from queue, build + POST one by one.

        For manual jobs to multi-cred marketplaces (Eldorado, GameBoost),
        all items are drained first and posted as a single multi-credential
        offer.  For all other jobs (including PA), items are processed one
        by one as they arrive (streaming).
        """
        try:
            close_old_connections()

            # Multi-cred: manual jobs to marketplaces that accept multiple
            # credentials in a single offer (Eldorado, GameBoost).  Peek the
            # first entry to learn the marketplace; if sentinel comes first
            # the queue is empty — nothing to do.
            first_entry = queue.get()
            if first_entry is self._sentinel:
                return
            first_marketplace = first_entry[0].marketplace
            if self._is_multi_cred_job(job, first_marketplace):
                entries: list[tuple[PostingJobItem, dict]] = [first_entry]
                while True:
                    entry = queue.get()
                    if entry is self._sentinel:
                        break
                    entries.append(entry)
                if entries:
                    self._process_multi_cred_batch(entries, job)
                return
            # Not multi-cred — put the first entry back into processing below
            remaining_first = first_entry

            # ── PA relay batch path — all PA items go through relay, never direct SDK ──
            if first_marketplace == 'playerauctions':
                entries_pa: list[tuple[PostingJobItem, dict]] = [first_entry]
                while True:
                    entry = queue.get()
                    if entry is self._sentinel:
                        break
                    entries_pa.append(entry)
                if entries_pa:
                    self._process_pa_relay_batch(entries_pa, job)
                return

            # ── Standard streaming path — process each item as it arrives ──
            variant_ctx: dict | None = None
            router: VariantRouter | None = None
            _routing_init = False

            # Process the already-dequeued first entry, then continue draining
            def _drain():
                yield remaining_first
                while True:
                    entry = queue.get()
                    if entry is self._sentinel:
                        return
                    yield entry

            for entry in _drain():
                item, prepared_data = entry

                if self._is_cancelled(job):
                    item.status = PostingJobItemStatus.SKIPPED
                    item.error_message = 'Job cancelled'
                    item.save(update_fields=[
                        'status', 'error_message', 'updated_at',
                    ])
                    continue

                if self._rate_limit_event.is_set():
                    item.status = PostingJobItemStatus.SKIPPED
                    item.error_message = 'Job stopped: rate limit exhausted'
                    item.save(update_fields=[
                        'status', 'error_message', 'updated_at',
                    ])
                    continue

                if not _routing_init:
                    variant_ctx = build_variant_context(
                        store=item.store, game=job.game,
                        marketplace=item.marketplace,
                    )
                    router = VariantRouter(variant_ctx, mode='stock')
                    _routing_init = True

                self._process_item(
                    item, prepared_data, job,
                    variant_ctx=variant_ctx, router=router,
                )

                # Throttle between items — wake immediately on cancel
                self._cancel_event.wait(timeout=10)

        finally:
            close_old_connections()

    def _process_item(
        self,
        item: PostingJobItem,
        prepared_data: dict,
        job: PostingJob,
        *,
        variant_ctx: dict | None = None,
        router: VariantRouter | None = None,
    ) -> None:
        """Process a single non-PA item: build payload → POST → create Listing.

        Failure stages are separated into two try blocks so that
        release_dispatch_items_for_job can use the correct remote_outcome:
        - Pre-remote (build fail, API net error): remote_outcome='absent'
        - Post-remote (persist fail after confirmed API success): remote_outcome='unknown'
        """
        from apps.posting.services.pool.dispatcher import release_dispatch_items_for_job

        item.status = PostingJobItemStatus.PROCESSING
        item.save(update_fields=['status', 'updated_at'])

        owned_product = prepared_data.get('owned_product')

        # ── Stage 1: build + remote POST ──────────────────────────────────
        store_listing_id = None
        api_data = None
        payload = None
        final_price = None
        variant_slug = None
        listing_variant_slug = None

        try:
            build_result = build_item_payload(
                item, prepared_data, job,
                variant_ctx=variant_ctx, router=router,
            )

            if not build_result['ok']:
                raise ValueError(
                    f"[{build_result['stage']}] {build_result['error']}"
                )

            payload = build_result['data']['payload']
            final_price = build_result['data']['final_price']
            variant_slug = build_result['data']['variant_slug']
            listing_variant_slug = build_result['data'].get(
                'listing_variant_slug', variant_slug,
            )

            api_result = self._post_with_backoff(item, payload)

            if not api_result.ok:
                # Variant fallback: try other variants on max offer error
                if (
                    is_max_offer_error(api_result)
                    and item.marketplace == 'eldorado'
                    and job.game.slug in PLATFORM_PRIORITY
                ):
                    fallback_result = self._retry_with_variant_fallback(
                        item, prepared_data, job,
                        excluded=[variant_slug],
                        router=router,
                    )
                    if fallback_result:
                        return  # success via fallback

                err = api_result.error
                api_messages: list[str] = []
                if isinstance(err.details, dict):
                    msgs = err.details.get('messages')
                    if isinstance(msgs, list):
                        api_messages = [str(m) for m in msgs if m]
                detail_text = "; ".join(api_messages) if api_messages else err.message
                raise RuntimeError(
                    f"API error: {detail_text} (category={err.category})"
                )

            store_listing_id = extract_listing_id(api_result.data)
            api_data = api_result.data

            # GameBoost: publish the newly created offer (draft → listed)
            if item.marketplace == 'gameboost':
                self._list_gameboost_offer(item, store_listing_id)

        except Exception as e:
            item.status = PostingJobItemStatus.FAILED
            item.error_message = str(e)
            logger.exception("Item #%d failed (pre-remote): %s", item.id, e)

            if owned_product:
                add_failed_owned_products_to_pool(job, [owned_product])
                release_dispatch_items_for_job(
                    job, owned_products=[owned_product],
                    reason=str(e), remote_outcome='absent',
                )

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
            return

        # ── Stage 2: persist listing (post-remote) ────────────────────────
        # At this point the offer EXISTS on the marketplace.
        # Any failure here → remote_outcome='unknown'.
        try:
            normalized_raw = self._normalize_raw_data(
                item,
                api_data,
                payload=payload,
            )

            persist_success(
                item=item,
                job=job,
                owned_product=owned_product,
                store_listing_id=store_listing_id,
                variant_slug=listing_variant_slug,
                final_price=final_price,
                payload=payload,
                response_data=api_data,
                raw_data_override=normalized_raw,
            )

            # Update in-memory counter so next item sees correct capacity
            if router is not None and variant_slug:
                router.record_post('platform', variant_slug)

        except Exception as e:
            item.status = PostingJobItemStatus.FAILED
            item.error_message = f'Listing persist failed (offer may exist remotely): {e}'
            logger.exception(
                "Item #%d persist failed after successful API call (store_listing_id=%s): %s",
                item.id, store_listing_id, e,
            )

            if owned_product:
                release_dispatch_items_for_job(
                    job, owned_products=[owned_product],
                    reason=str(e), remote_outcome='unknown',
                )

            PostingLog.objects.create(
                task_name='stock_post',
                level=PostingLogLevel.ERROR,
                message=f"Persist failed after API success: {item.login} → {item.store.name}",
                detail={
                    'item_id': item.id,
                    'job_id': job.id,
                    'stage': 'persist_success',
                    'store_listing_id': store_listing_id,
                    'error': str(e),
                },
                integration_account=item.store,
            )

        item.save(update_fields=['status', 'error_message', 'listing', 'updated_at'])

    # ------------------------------------------------------------------
    # Multi-credential batch (GTA manual → single offer)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_multi_cred_job(job: PostingJob, marketplace: str) -> bool:
        """Return True when all credentials should be merged into one offer.

        Multi-cred is enabled for manual jobs targeting marketplaces that
        accept multiple credentials per offer (Eldorado, GameBoost).
        PlayerAuctions requires one offer per credential.
        """
        manual = job.settings.get('_manual', {})
        return (
            isinstance(manual, dict)
            and manual.get('source_type') == 'manual'
            and marketplace in _MULTI_CRED_MARKETPLACES
        )

    def _process_multi_cred_batch(
        self,
        entries: list[tuple[PostingJobItem, dict]],
        job: PostingJob,
    ) -> None:
        """Build one payload from all credentials and POST a single multi-cred offer.

        Steps:
        1. Build individual payloads for each item (to extract credential strings).
        2. Merge all credential strings into the first payload.
        3. POST once → create one Listing → link all items to it.
        """
        first_item = entries[0][0]
        marketplace = first_item.marketplace

        # Variant context — same for all items in this store thread
        variant_ctx = build_variant_context(
            store=first_item.store, game=job.game,
            marketplace=marketplace,
        )
        router = VariantRouter(variant_ctx, mode='stock')

        # Build payload for each entry and collect results
        build_results: list[tuple[PostingJobItem, dict, dict]] = []
        for item, prepared_data in entries:
            if self._is_cancelled(job):
                item.status = PostingJobItemStatus.SKIPPED
                item.error_message = 'Job cancelled'
                item.save(update_fields=['status', 'error_message', 'updated_at'])
                continue

            result = build_item_payload(
                item, prepared_data, job,
                variant_ctx=variant_ctx, router=router,
            )
            if not result['ok']:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = f"[{result['stage']}] {result['error']}"
                item.save(update_fields=['status', 'error_message', 'updated_at'])
                PostingLog.objects.create(
                    task_name='stock_post',
                    level=PostingLogLevel.ERROR,
                    message=f"Multi-cred build failed: {item.login}",
                    detail={
                        'item_id': item.id, 'job_id': job.id,
                        'stage': result['stage'], 'error': result['error'],
                    },
                    integration_account=item.store,
                )
                continue

            build_results.append((item, prepared_data, result))

        if not build_results:
            return

        # Use first successful build as base payload
        base_item, base_prepared, base_result = build_results[0]
        base_payload = base_result['data']['payload']
        final_price = base_result['data']['final_price']
        variant_slug = base_result['data']['variant_slug']
        listing_variant_slug = base_result['data'].get(
            'listing_variant_slug', variant_slug,
        )

        # Merge credentials into single payload
        if marketplace == 'eldorado':
            all_creds: list[str] = []
            for _, _, r in build_results:
                creds = r['data']['payload'].get('accountSecretDetails', [])
                all_creds.extend(creds)
            base_payload['accountSecretDetails'] = all_creds
            base_payload['details']['pricing']['quantity'] = len(all_creds)

        elif marketplace == 'gameboost':
            # Collect delivery_instructions from each payload as credential strings
            all_creds = []
            for _, _, r in build_results:
                cred_text = r['data']['payload'].get('delivery_instructions', '')
                if cred_text:
                    all_creds.append(cred_text)
            # Convert from legacy single-cred to multi-cred format
            for field in ('login', 'password', 'email_login', 'email_password', 'mail_provider'):
                base_payload.pop(field, None)
            base_payload.pop('delivery_instructions', None)
            base_payload['credentials'] = all_creds

        # Mark all items as PROCESSING
        all_items = [item for item, _, _ in build_results]
        for item in all_items:
            item.status = PostingJobItemStatus.PROCESSING
            item.save(update_fields=['status', 'updated_at'])

        logger.info(
            "Multi-cred POST: %d credentials → %s (job=%d, store=%s)",
            len(build_results), marketplace, job.id, base_item.store.name,
        )

        from apps.posting.services.pool.dispatcher import release_dispatch_items_for_job

        # ── Stage 1: remote POST ───────────────────────────────────────────
        store_listing_id = None
        api_data = None
        try:
            api_result = self._post_with_backoff(base_item, base_payload)

            if not api_result.ok:
                err = api_result.error
                api_messages: list[str] = []
                if isinstance(err.details, dict):
                    msgs = err.details.get('messages')
                    if isinstance(msgs, list):
                        api_messages = [str(m) for m in msgs if m]
                detail_text = "; ".join(api_messages) if api_messages else err.message
                raise RuntimeError(
                    f"API error: {detail_text} (category={err.category})"
                )

            store_listing_id = extract_listing_id(api_result.data)
            api_data = api_result.data

            if marketplace == 'gameboost':
                self._list_gameboost_offer(base_item, store_listing_id)

        except Exception as e:
            logger.exception(
                "Multi-cred POST failed (job=%d, store=%s): %s",
                job.id, base_item.store.name, e,
            )
            for item in all_items:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = str(e)
                item.save(update_fields=['status', 'error_message', 'updated_at'])
            failed_owned = [pd['owned_product'] for _, pd, _ in build_results if pd.get('owned_product')]
            add_failed_owned_products_to_pool(job, failed_owned)
            release_dispatch_items_for_job(
                job, owned_products=failed_owned,
                reason=str(e), remote_outcome='absent',
            )
            PostingLog.objects.create(
                task_name='stock_post',
                level=PostingLogLevel.ERROR,
                message=f"Multi-cred POST failed → {base_item.store.name}",
                detail={
                    'job_id': job.id,
                    'credential_count': len(all_items),
                    'error': str(e),
                },
                integration_account=base_item.store,
            )
            return

        # ── Stage 2: persist listing (post-remote) ────────────────────────
        try:
            normalized_raw = self._normalize_raw_data(
                base_item, api_data, payload=base_payload,
            )

            # Persist: create ONE listing, link ALL owned_products
            owned_products = [pd['owned_product'] for _, pd, _ in build_results]
            listing = persist_multi_cred_success(
                items=all_items,
                job=job,
                owned_products=owned_products,
                store_listing_id=store_listing_id,
                variant_slug=listing_variant_slug,
                final_price=final_price,
                payload=base_payload,
                response_data=api_data,
                raw_data_override=normalized_raw,
            )

            if router is not None and variant_slug:
                router.record_post('platform', variant_slug)

            logger.info(
                "Multi-cred success: listing #%d with %d credentials (offer=%s)",
                listing.id, len(all_items), store_listing_id,
            )

        except Exception as e:
            logger.exception(
                "Multi-cred persist failed after API success (job=%d, store_listing_id=%s): %s",
                job.id, store_listing_id, e,
            )
            for item in all_items:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = f'Listing persist failed (offer may exist remotely): {e}'
                item.save(update_fields=['status', 'error_message', 'updated_at'])
            failed_owned = [pd['owned_product'] for _, pd, _ in build_results if pd.get('owned_product')]
            release_dispatch_items_for_job(
                job, owned_products=failed_owned,
                reason=str(e), remote_outcome='unknown',
            )
            PostingLog.objects.create(
                task_name='stock_post',
                level=PostingLogLevel.ERROR,
                message=f"Multi-cred persist failed after API success → {base_item.store.name}",
                detail={
                    'job_id': job.id,
                    'store_listing_id': store_listing_id,
                    'error': str(e),
                },
                integration_account=base_item.store,
            )

    def _process_pa_relay_batch(
        self,
        entries: list[tuple],
        job,
    ) -> None:
        """Route all PA items through the relay poster — never direct SDK calls.
        Collects all items for a store, builds payload dicts, posts via
        PARelayPoster, then persists results.
        """
        import logging
        from apps.posting.models import PostingJobItemStatus, PostingLog, PostingLogLevel
        from apps.posting.services.pool.dispatcher import release_dispatch_items_for_job
        from apps.posting.services.stock.pa_relay_poster import PARelayPoster, fetch_relay_token
        from apps.posting.services.stock.pipeline import build_item_payload
        from apps.posting.services.stock.persist import persist_success
        from apps.posting.services.pool.pool import add_failed_owned_products_to_pool
        from apps.posting.services.stock.normalize import normalize_offer_response
        from apps.posting.services.stock.variant_router import VariantRouter, build_variant_context

        logger = logging.getLogger(__name__)

        if not entries:
            return

        first_item = entries[0][0]
        store = first_item.store
        creds = store.credential.credentials or {}
        store_slug = creds.get('store_slug', '')
        relay_url = creds.get('relay_url', 'http://35.196.132.30:3001')
        relay_secret = creds.get('relay_secret', 'pa-relay-secret-2026')

        # Use cached access token from DB, or fetch fresh from relay
        relay_token = creds.get('access_token') or creds.get('bearer_token') or ''
        if not relay_token:
            username = creds.get('username', '')
            password = creds.get('password', '')
            if username and password and store_slug:
                logger.info(
                    "PA relay token not cached — fetching fresh for store=%s (job=%d)",
                    store_slug, job.id,
                )
                relay_token = fetch_relay_token(
                    username, password, store_slug,
                    relay_url=relay_url, relay_secret=relay_secret,
                )

        if not relay_token or not store_slug:
            logger.error(
                "PA relay: no token/store_slug for store=%s (job=%d) — marking all failed",
                store_slug, job.id,
            )
            for item, prepared_data in entries:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = 'PA relay token unavailable — check relay machine and store credentials'
                item.save(update_fields=['status', 'error_message', 'updated_at'])
                owned_product = prepared_data.get('owned_product')
                if owned_product:
                    add_failed_owned_products_to_pool(job, [owned_product])
                    release_dispatch_items_for_job(
                        job, owned_products=[owned_product],
                        reason='PA relay token unavailable', remote_outcome='absent',
                    )
            return

        # Build payload rows for each item
        variant_ctx = build_variant_context(
            store=store, game=job.game, marketplace='playerauctions',
        )
        router = VariantRouter(variant_ctx, mode='stock')
        excel_rows: list[dict] = []
        build_data_list: list[dict] = []
        valid_entries: list[tuple] = []

        for item, prepared_data in entries:
            try:
                build_result = build_item_payload(
                    item, prepared_data, job,
                    variant_ctx=variant_ctx, router=router,
                )
                if not build_result['ok']:
                    raise ValueError(f"[{build_result['stage']}] {build_result['error']}")
                excel_rows.append(build_result['data']['payload'])
                build_data_list.append(build_result['data'])
                valid_entries.append((item, prepared_data))
            except Exception as exc:
                item.status = PostingJobItemStatus.FAILED
                item.error_message = str(exc)
                item.save(update_fields=['status', 'error_message', 'updated_at'])
                owned_product = prepared_data.get('owned_product')
                if owned_product:
                    add_failed_owned_products_to_pool(job, [owned_product])
                    release_dispatch_items_for_job(
                        job, owned_products=[owned_product],
                        reason=str(exc), remote_outcome='absent',
                    )

        if not excel_rows:
            return

        # Post via relay
        logger.info("PA relay batch: %d rows (job=%d, store=%s)", len(excel_rows), job.id, store_slug)
        _relay_poster = PARelayPoster()
        _relay_result = _relay_poster.post_batch(relay_token, store_slug, excel_rows)

        # Build PA client for normalize_offer_response (optional, graceful fallback)
        facade = None
        proxy_group = None
        try:
            from apps.posting.services.stock.proxy import get_group_name
            from apps.posting.services.stock.registry import registry
            proxy_group = get_group_name(store)
            facade = registry.get_or_build_client(
                'playerauctions', store.credential,
                proxy_pool=self._proxy_pool, proxy_group=proxy_group,
            )
        except Exception:
            pass

        for idx, (item, prepared_data) in enumerate(valid_entries):
            owned_product = prepared_data.get('owned_product')
            if idx in _relay_result.successful:
                offer_id = _relay_result.successful[idx]
                final_price = build_data_list[idx]['final_price']
                variant_slug = build_data_list[idx]['variant_slug']
                listing_variant_slug = build_data_list[idx].get('listing_variant_slug', variant_slug)
                try:
                    kwargs = {}
                    if facade:
                        kwargs['client'] = facade
                        kwargs['proxy_group'] = proxy_group
                    normalized_raw = normalize_offer_response(
                        'playerauctions',
                        {'offer_id': offer_id},
                        payload=excel_rows[idx],
                        **kwargs,
                    )
                    persist_success(
                        item=item,
                        job=job,
                        owned_product=owned_product,
                        store_listing_id=offer_id,
                        variant_slug=listing_variant_slug,
                        final_price=final_price,
                        payload=excel_rows[idx],
                        response_data={'offer_id': offer_id},
                        raw_data_override=normalized_raw,
                    )
                except Exception as exc:
                    item.status = PostingJobItemStatus.FAILED
                    item.error_message = f'Listing persist failed (PA offer may exist): {exc}'
                    logger.exception(
                        "PA listing persist failed for item #%d (offer_id=%s)", item.id, offer_id,
                    )
                    release_dispatch_items_for_job(
                        job, owned_products=[owned_product] if owned_product else [],
                        reason=str(exc), remote_outcome='unknown',
                    )
            else:
                error_msg = _relay_result.failed.get(idx, 'PA relay post failed')
                item.status = PostingJobItemStatus.FAILED
                item.error_message = error_msg
                if owned_product:
                    add_failed_owned_products_to_pool(job, [owned_product])
                    release_dispatch_items_for_job(
                        job, owned_products=[owned_product],
                        reason=error_msg, remote_outcome='absent',
                    )
                PostingLog.objects.create(
                    task_name='stock_post',
                    level=PostingLogLevel.ERROR,
                    message=f"PA relay post failed: {item.login}",
                    detail={
                        'item_id': item.id,
                        'job_id': job.id,
                        'stage': 'pa_relay_batch',
                        'error': error_msg,
                    },
                    integration_account=store,
                )
            item.save(update_fields=['status', 'error_message', 'listing', 'updated_at'])

    def _retry_with_variant_fallback(
        self,
        item: PostingJobItem,
        prepared_data: dict,
        job: PostingJob,
        *,
        excluded: list[str],
        router: VariantRouter | None,
    ) -> bool:
        """Try posting with alternative variants when max offer limit is hit.

        Iterates through available variants (excluding already-tried ones).
        Returns True if any variant succeeds.
        """
        game_slug = job.game.slug
        tiers = PLATFORM_PRIORITY.get(game_slug, [])
        all_variants = [slug for tier in tiers for slug in tier]
        available = [v for v in all_variants if v not in excluded]

        # Build context once — it's variant-independent (DB counts + limits)
        fresh_ctx = build_variant_context(
            store=item.store, game=job.game, marketplace=item.marketplace,
        )

        for candidate in available:
            fresh_router = VariantRouter(fresh_ctx, mode='stock')

            build_result = build_item_payload(
                item, prepared_data, job,
                variant_ctx=fresh_ctx,
                router=fresh_router,
                force_variant=candidate,
            )

            if not build_result['ok']:
                continue

            payload = build_result['data']['payload']
            final_price = build_result['data']['final_price']
            variant_slug = build_result['data']['variant_slug']
            listing_variant_slug = build_result['data'].get(
                'listing_variant_slug', variant_slug,
            )

            api_result = self._post_with_backoff(item, payload)

            if api_result.ok:
                store_listing_id = extract_listing_id(api_result.data)

                normalized_raw = self._normalize_raw_data(
                    item, api_result.data, payload=payload,
                )

                persist_success(
                    item=item,
                    job=job,
                    owned_product=prepared_data['owned_product'],
                    store_listing_id=store_listing_id,
                    variant_slug=listing_variant_slug,
                    final_price=final_price,
                    payload=payload,
                    response_data=api_result.data,
                    raw_data_override=normalized_raw,
                )

                if router is not None and variant_slug:
                    router.record_post('platform', variant_slug)

                logger.info(
                    "Variant fallback succeeded: item #%d → variant=%s (tried %d)",
                    item.id, variant_slug, len(excluded) + 1,
                )
                return True

            if is_max_offer_error(api_result):
                excluded.append(candidate)
                continue

            # Different error — stop trying
            break

        logger.warning(
            "All variants exhausted for item #%d (%s/%s)",
            item.id, game_slug, item.store.name,
        )
        return False

    def _normalize_raw_data(
        self,
        item: PostingJobItem,
        response_data: object,
        *,
        payload: dict,
    ) -> dict | None:
        if item.marketplace not in {'eldorado', 'gameboost', 'playerauctions'}:
            return None

        kwargs = {}
        if item.marketplace == 'playerauctions':
            proxy_group = get_group_name(item.store)
            kwargs['client'] = registry.get_or_build_client(
                item.marketplace,
                item.store.credential,
                proxy_pool=self._proxy_pool,
                proxy_group=proxy_group,
            )
            kwargs['proxy_group'] = proxy_group

        return normalize_offer_response(
            item.marketplace,
            response_data,
            payload=payload,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # GameBoost post-create: publish offer
    # ------------------------------------------------------------------

    def _list_gameboost_offer(
        self,
        item: PostingJobItem,
        store_listing_id: str,
    ) -> None:
        """Call POST /account-offers/{id}/list to publish a GameBoost offer."""
        from apps.integrations.providers import registry
        from apps.integrations.proxy_pool import get_group_name

        proxy_group = get_group_name(item.store)
        facade = registry.get_or_build_client(
            item.marketplace, item.store.credential,
            proxy_pool=self._proxy_pool,
            proxy_group=proxy_group,
        )
        result = facade.list_account_offer(
            store_listing_id, proxy_group=proxy_group,
        )
        if not result.ok:
            logger.warning(
                "GameBoost list action failed for offer %s (store=%s): %s",
                store_listing_id, item.store.name,
                getattr(result.error, 'message', result.error),
            )

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

            # Lazily initialised once from the first item
            variant_ctx: dict | None = None
            router: VariantRouter | None = None
            _routing_init = False

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

                # Build variant routing once per store thread
                if not _routing_init:
                    variant_ctx = build_variant_context(
                        store=item.store, game=job.game,
                        marketplace=item.marketplace,
                    )
                    router = VariantRouter(variant_ctx, mode='stock')
                    _routing_init = True

                build_result = build_item_payload(
                    item, prepared_data, job,
                    variant_ctx=variant_ctx, router=router,
                )

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

                # Update in-memory counter so next item sees correct capacity
                pa_variant_slug = build_data.get('variant_slug', '')
                if router is not None and pa_variant_slug:
                    router.record_post('platform', pa_variant_slug)

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

        # [RELAY-ALWAYS] All PA posting goes through relay — no XLSX fallback
        _auth = getattr(facade, '_auth', None)
        _relay_token = (_auth.access_token if _auth and _auth.access_token else None)
        _store_slug = (_auth._store_slug if _auth and getattr(_auth, '_store_slug', None) else None)

        # If no cached token, fetch fresh from relay using store credentials
        if not _relay_token or not _store_slug:
            _creds = {}
            _store = getattr(items[0], 'store', None) if items else None
            if _store and hasattr(_store, 'credential') and _store.credential:
                _creds = _store.credential.credentials or {}
            _username = _creds.get('username', '')
            _password = _creds.get('password', '')
            _store_slug = _creds.get('store_slug', '')
            _relay_url = _creds.get('relay_url', 'http://35.231.166.148:3001')
            _relay_secret = _creds.get('relay_secret', 'pa-relay-secret-2026')
            if _username and _password and _store_slug:
                logger.info(
                    "PA relay token not cached — fetching fresh for store=%s (job=%d)",
                    _store_slug, job.id,
                )
                _relay_token = fetch_relay_token(
                    _username, _password, _store_slug,
                    relay_url=_relay_url, relay_secret=_relay_secret,
                )
            else:
                logger.error(
                    "PA relay: missing credentials for store (job=%d) — cannot post",
                    job.id,
                )

        if _relay_token and _store_slug:
            logger.info("PA flush via relay: %d rows (job=%d, store=%s)", len(excel_rows), job.id, _store_slug)
            _relay_poster = PARelayPoster()
            _relay_result = _relay_poster.post_batch(_relay_token, _store_slug, excel_rows)
            # Convert PARelayPostResult to PABatchResult for unified downstream handling
            batch_result = PABatchResult(
                successful=_relay_result.successful,
                failed=_relay_result.failed,
            )
        else:
            logger.error(
                "PA relay: no token available — marking all %d items as failed (job=%d)",
                len(items), job.id,
            )
            batch_result = PABatchResult(
                successful={},
                failed={i: "PA relay token unavailable — check relay machine and store credentials" for i in range(len(items))},
            )

        from apps.posting.services.pool.dispatcher import release_dispatch_items_for_job

        for idx, item in enumerate(items):
            if idx in batch_result.successful:
                offer_id = batch_result.successful[idx]
                final_price: Decimal = build_data_list[idx]['final_price']
                variant_slug: str = build_data_list[idx]['variant_slug']
                listing_variant_slug: str = build_data_list[idx].get(
                    'listing_variant_slug', variant_slug,
                )
                owned_product = prepared_data_list[idx]['owned_product']

                try:
                    normalized_raw = normalize_offer_response(
                        'playerauctions',
                        {'offer_id': offer_id},
                        payload=excel_rows[idx],
                        client=facade,
                        proxy_group=proxy_group,
                    )
                    persist_success(
                        item=item,
                        job=job,
                        owned_product=owned_product,
                        store_listing_id=offer_id,
                        variant_slug=listing_variant_slug,
                        final_price=final_price,
                        payload=excel_rows[idx],
                        response_data={'offer_id': offer_id},
                        raw_data_override=normalized_raw,
                    )
                except Exception as exc:
                    # PA accepted this offer — remote side effect exists.
                    item.status = PostingJobItemStatus.FAILED
                    item.error_message = f'Listing persist failed (PA offer may exist): {exc}'
                    logger.exception("PA listing persist failed for item #%d (offer_id=%s)", item.id, offer_id)
                    release_dispatch_items_for_job(
                        job, owned_products=[owned_product],
                        reason=str(exc), remote_outcome='unknown',
                    )
            else:
                error_msg = batch_result.failed.get(idx, 'PA upload failed')
                item.status = PostingJobItemStatus.FAILED
                item.error_message = error_msg
                owned_product = prepared_data_list[idx].get('owned_product')
                if owned_product:
                    add_failed_owned_products_to_pool(job, [owned_product])
                    release_dispatch_items_for_job(
                        job, owned_products=[owned_product],
                        reason=error_msg, remote_outcome='absent',
                    )
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
