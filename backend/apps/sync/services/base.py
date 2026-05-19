from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from apps.sync.enums import (
    CheckpointStatus,
    ParseStatus,
    ResourceType,
    SyncMode,
    SyncPhase,
    SyncRunStatus,
)
from apps.sync.exceptions import SkipItem, StopSync
from apps.sync.models import RawPayload, SyncCheckpoint, SyncRun

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


class BaseSyncService:
    """Shared orchestration logic for all resource sync services.

    Subclasses MUST implement:
        - resource_type: str
        - fetch_page(account, checkpoint) -> (items, next_cursor)
        - extract_remote_id(item) -> str
        - parse_and_apply(raw_payload) -> 'created' | 'updated' | None

    Subclasses MAY override:
        - extract_remote_timestamp(item) -> datetime | None
        - is_already_seen(item, stop_remote_id) -> bool
        - should_skip_item(item) -> bool
        - prepare_item(item, account) -> (item, extra_meta)

    Subclasses MUST NOT override ``_fetch_loop``. All provider-specific
    behavior is expressed through the hooks above.
    """

    resource_type: str = ''

    # ── Subclass hooks (MUST implement) ───────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of remote items.

        Returns ``(items, next_cursor)``. Empty ``next_cursor`` means
        no more pages.
        """
        raise NotImplementedError

    def extract_remote_id(self, item: dict) -> str:
        """Extract the unique remote identifier from a raw item."""
        raise NotImplementedError

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse ``raw_payload.payload`` and upsert into the domain table.

        Returns ``'created'``, ``'updated'``, or ``None``.
        """
        raise NotImplementedError

    # ── Subclass hooks (MAY override) ─────────────────────────────────

    def extract_remote_timestamp(self, item: dict):
        """Return a datetime or ``None`` from the raw item."""
        return None

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Return ``True`` if this item was already ingested.

        Used in incremental mode to stop early once we reach data that
        was already synced in a prior run. ``stop_remote_id`` is the
        snapshot taken at the start of the run — it does NOT change
        as the checkpoint advances.  Default: always ``False``.
        """
        return False

    def should_skip_item(self, item: dict) -> bool:
        """Return ``True`` to skip this item entirely.

        The item is counted as processed but NOT written to
        ``RawPayload``. Use for statuses that are not useful
        (e.g. PlayerAuctions "Pending Payment").
        """
        return False

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Transform or enrich an item BEFORE raw persistence.

        Returns ``(transformed_item, extra_meta)``. The ``extra_meta``
        dict is merged into ``RawPayload.meta``.

        Raise ``SkipItem`` to skip this item (no raw write).
        Raise ``StopSync`` to abort the entire sync run.
        """
        return item, {}

    # ── Orchestration ────────────────────────────────────────────────

    def run(
        self,
        account: IntegrationAccount,
        mode: str,
        phase: str = SyncPhase.FULL,
    ) -> SyncRun | None:
        """Execute a sync run for one account.

        Args:
            account: The integration account to sync.
            mode: ``SyncMode.BACKFILL`` or ``SyncMode.INCREMENTAL``.
            phase: ``SyncPhase.FULL``, ``INGEST``, or ``PROCESS``.

        Returns:
            The ``SyncRun`` audit record, or ``None`` if the backfill
            checkpoint is already completed.
        """
        self._phase = phase

        # ── Process-only: no API calls, just parse pending raws ───────
        if phase == SyncPhase.PROCESS:
            run = SyncRun.objects.create(
                integration_account=account,
                resource_type=self.resource_type,
                mode=mode,
            )
            logger.info(
                "SyncRun %s started (process-only): account=%s resource=%s",
                run.pk, account.slug, self.resource_type,
            )
            try:
                self._process_pending(account, run)
                run.finish(SyncRunStatus.COMPLETED)
            except Exception:
                logger.exception("SyncRun %s failed (process-only)", run.pk)
                run.finish(SyncRunStatus.FAILED)
                raise
            return run

        # ── Ingest (+ optional process) ──────────────────────────────
        checkpoint = self._get_or_create_checkpoint(account, mode)

        if (
            mode == SyncMode.BACKFILL
            and checkpoint.status == CheckpointStatus.COMPLETED
        ):
            logger.info(
                "Backfill checkpoint already completed for account=%s "
                "resource=%s. Reset the checkpoint to re-run.",
                account.slug, self.resource_type,
            )
            return None

        # Clear transient run-scoped meta keys from prior runs
        transient_keys = ('_incremental_page', '_current_status')
        if any(k in checkpoint.meta for k in transient_keys):
            for k in transient_keys:
                checkpoint.meta.pop(k, None)
            checkpoint.save(update_fields=['meta', 'updated_at'])

        run = SyncRun.objects.create(
            integration_account=account,
            resource_type=self.resource_type,
            mode=mode,
        )

        logger.info(
            "SyncRun %s started: account=%s resource=%s mode=%s phase=%s",
            run.pk, account.slug, self.resource_type, mode, phase,
        )

        try:
            exhausted = self._fetch_loop(account, checkpoint, run)

            if mode == SyncMode.BACKFILL and exhausted:
                checkpoint.status = CheckpointStatus.COMPLETED
                checkpoint.save(update_fields=['status', 'updated_at'])
                self._seed_incremental_checkpoint(account, checkpoint)
                self._reconcile_stale(account, run)

            run.finish(SyncRunStatus.COMPLETED)

        except StopSync as exc:
            logger.error(
                "SyncRun %s stopped: %s", run.pk, exc.message,
            )
            run.meta = {**run.meta, 'stop_reason': exc.message}
            run.finish(SyncRunStatus.FAILED)
            raise

        except Exception:
            logger.exception("SyncRun %s failed", run.pk)
            run.finish(SyncRunStatus.FAILED)
            raise

        logger.info(
            "SyncRun %s finished: processed=%d created=%d "
            "updated=%d errors=%d",
            run.pk, run.processed_count, run.created_count,
            run.updated_count, run.error_count,
        )
        return run

    # ── Core fetch loop (NOT to be overridden) ────────────────────────

    def _fetch_loop(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
        run: SyncRun,
    ) -> bool:
        """Page through remote data, ingest, then optionally parse.

        Returns ``True`` if the source was exhausted (no more pages).

        Provider-specific behavior is injected via hooks:
        - ``should_skip_item`` — skip unwanted items
        - ``prepare_item`` — transform/enrich before raw persistence
        - ``is_already_seen`` — incremental stop condition

        Incremental note: ``stop_remote_id`` is snapshot ONCE before the
        loop starts so that checkpoint.advance() cannot shift the goal-post.
        After the loop, ``last_seen_remote_id`` is set to the NEWEST item
        (first item of the first page) so the next run starts from there.
        """
        is_incremental = checkpoint.mode == SyncMode.INCREMENTAL
        stop_remote_id = checkpoint.last_seen_remote_id if is_incremental else ''

        fetched_any = False
        caught_up = False
        first_remote_id: str | None = None
        first_remote_ts = None

        while True:
            items, next_cursor = self.fetch_page(account, checkpoint)
            if not items:
                break

            fetched_any = True

            with transaction.atomic():
                last_remote_id: str | None = None
                last_remote_ts = None

                for item in items:
                    # Incremental stop condition
                    if is_incremental and self.is_already_seen(
                        item, stop_remote_id,
                    ):
                        caught_up = True
                        logger.info(
                            "Incremental sync caught up at remote_id=%s",
                            self.extract_remote_id(item),
                        )
                        break

                    remote_id = self._validated_remote_id(item)
                    remote_ts = self.extract_remote_timestamp(item)

                    # Track the first (newest) item for incremental bookmark
                    if first_remote_id is None:
                        first_remote_id = remote_id
                        first_remote_ts = remote_ts

                    # Status-based skip (e.g. PA "Pending Payment")
                    if self.should_skip_item(item):
                        run.processed_count += 1
                        last_remote_id = remote_id
                        last_remote_ts = remote_ts
                        continue

                    # Transform / enrich
                    try:
                        prepared_item, extra_meta = self.prepare_item(
                            item, account,
                        )
                    except SkipItem:
                        run.processed_count += 1
                        run.error_count += 1
                        last_remote_id = remote_id
                        last_remote_ts = remote_ts
                        continue
                    # StopSync propagates up — caught by run()

                    # Persist raw payload
                    raw = self._ingest_raw(account, remote_id, prepared_item)

                    if extra_meta:
                        raw.meta = {**raw.meta, **extra_meta}
                        raw.save(update_fields=['meta', 'updated_at'])

                    # Parse (unless ingest-only)
                    if self._phase != SyncPhase.INGEST:
                        self._try_parse(raw, run)

                    last_remote_id = remote_id
                    last_remote_ts = remote_ts
                    run.processed_count += 1

                # Checkpoint: advance cursor always, but for incremental
                # keep last_seen_remote_id pointing to the newest item.
                if last_remote_id:
                    if is_incremental and first_remote_id:
                        checkpoint.advance(
                            remote_id=first_remote_id,
                            remote_timestamp=first_remote_ts,
                            cursor=next_cursor,
                        )
                    else:
                        checkpoint.advance(
                            remote_id=last_remote_id,
                            remote_timestamp=last_remote_ts,
                            cursor=next_cursor,
                        )

                # Persist run counters periodically
                run.save(update_fields=[
                    'processed_count', 'created_count',
                    'updated_count', 'error_count',
                    'meta', 'updated_at',
                ])

            if caught_up or not next_cursor:
                break

        # Incremental: reset cursor so the next run starts from the
        # initial cursor (e.g. newest-first "9999-...") instead of
        # resuming deeper into old data.
        if is_incremental and checkpoint.cursor:
            checkpoint.cursor = ''
            checkpoint.save(update_fields=['cursor', 'updated_at'])

        return fetched_any and not next_cursor

    # ── Process phase ────────────────────────────────────────────────

    def _process_pending(
        self,
        account: IntegrationAccount,
        run: SyncRun,
    ) -> None:
        """Parse all PENDING ``RawPayload`` rows for this account+resource."""
        pending = RawPayload.objects.filter(
            integration_account=account,
            resource_type=self.resource_type,
            parse_status=ParseStatus.PENDING,
        ).order_by('fetched_at')

        for raw in pending.iterator():
            self._try_parse(raw, run)

        run.save(update_fields=[
            'processed_count', 'created_count',
            'updated_count', 'error_count', 'updated_at',
        ])

    # ── Checkpoint helpers ───────────────────────────────────────────

    def _get_or_create_checkpoint(
        self,
        account: IntegrationAccount,
        mode: str,
    ) -> SyncCheckpoint:
        checkpoint, _ = SyncCheckpoint.objects.get_or_create(
            integration_account=account,
            resource_type=self.resource_type,
            mode=mode,
            defaults={'status': CheckpointStatus.ACTIVE},
        )
        return checkpoint

    def _seed_incremental_checkpoint(
        self,
        account: IntegrationAccount,
        backfill_cp: SyncCheckpoint,
    ) -> None:
        """Seed the incremental checkpoint from a completed backfill.

        After backfill finishes, the incremental checkpoint needs a
        starting ``last_seen_remote_id`` so that the first incremental
        run knows where to stop. Without this, incremental would
        re-scan everything.
        """
        inc_cp, created = SyncCheckpoint.objects.get_or_create(
            integration_account=account,
            resource_type=self.resource_type,
            mode=SyncMode.INCREMENTAL,
            defaults={
                'last_seen_remote_id': backfill_cp.last_seen_remote_id,
                'last_seen_remote_timestamp': backfill_cp.last_seen_remote_timestamp,
                'status': CheckpointStatus.ACTIVE,
            },
        )

        if not created and not inc_cp.last_seen_remote_id:
            inc_cp.last_seen_remote_id = backfill_cp.last_seen_remote_id
            inc_cp.last_seen_remote_timestamp = backfill_cp.last_seen_remote_timestamp
            inc_cp.save(update_fields=[
                'last_seen_remote_id',
                'last_seen_remote_timestamp',
                'updated_at',
            ])

        logger.info(
            "Incremental checkpoint seeded from backfill: "
            "last_seen_remote_id=%s",
            backfill_cp.last_seen_remote_id,
        )

    # ── Backfill reconciliation ─────────────────────────────────────

    def _reconcile_stale(
        self,
        account: IntegrationAccount,
        run: SyncRun,
    ) -> None:
        """Close listings not seen during a completed backfill.

        After a successful full backfill, any listing whose matching
        ``RawPayload.last_seen_at`` is older than the run start time
        was NOT returned by the remote API — it no longer exists
        upstream.

        Uses RawPayload.last_seen_at (always updated during ingest)
        instead of Listing.last_synced_at (only updated when payload
        hash changes and parse runs).

        Only applies to LISTINGS resource type. Orders are never
        removed from remote, so they are not reconciled.
        """
        if self.resource_type != ResourceType.LISTINGS:
            return

        from apps.listings.enums import ListingStatus
        from apps.listings.models import Listing

        now = timezone.now()

        # Find stale RawPayload remote_ids (not seen during this backfill)
        stale_raw_qs = RawPayload.objects.filter(
            integration_account=account,
            resource_type=self.resource_type,
            last_seen_at__lt=run.created_at,
        )
        stale_remote_ids = set(
            stale_raw_qs.values_list('remote_id', flat=True),
        )

        # Mark stale listings as DELETED (not seen during backfill = gone from marketplace)
        deleted_count = 0
        if stale_remote_ids:
            deleted_count = Listing.objects.filter(
                integration_account=account,
                store_listing_id__in=stale_remote_ids,
            ).exclude(
                status__in=[ListingStatus.CLOSED, ListingStatus.DELETED],
            ).update(
                status=ListingStatus.DELETED,
                removed_at=now,
            )

        # Hard-delete stale RawPayload rows
        raw_deleted_count, _ = stale_raw_qs.delete()

        if deleted_count or raw_deleted_count:
            logger.info(
                "Reconciliation: marked %d stale listings as deleted, "
                "deleted %d stale raw payloads for account=%s",
                deleted_count, raw_deleted_count, account.slug,
            )
            run.meta = {
                **run.meta,
                'reconciled_deleted': deleted_count,
                'reconciled_raw_deleted': raw_deleted_count,
            }
            run.save(update_fields=['meta', 'updated_at'])

    # ── Raw payload ingestion ────────────────────────────────────────

    def _ingest_raw(
        self,
        account: IntegrationAccount,
        remote_id: str,
        item: dict,
    ) -> RawPayload:
        """Write or update the raw payload row."""
        now = timezone.now()
        payload_hash = self._hash_payload(item)

        raw, created = RawPayload.objects.get_or_create(
            integration_account=account,
            resource_type=self.resource_type,
            remote_id=remote_id,
            defaults={
                'payload': item,
                'payload_hash': payload_hash,
                'first_seen_at': now,
                'last_seen_at': now,
                'fetched_at': now,
                'parse_status': ParseStatus.PENDING,
            },
        )

        if not created:
            raw.last_seen_at = now
            raw.fetched_at = now
            if raw.payload_hash != payload_hash:
                # Payload changed — store new version and request re-parse
                raw.payload = item
                raw.payload_hash = payload_hash
                raw.parse_status = ParseStatus.PENDING
                raw.parse_error = ''
                raw.parsed_at = None
                raw.save(update_fields=[
                    'payload', 'payload_hash', 'parse_status',
                    'parse_error', 'parsed_at',
                    'last_seen_at', 'fetched_at', 'updated_at',
                ])
            else:
                raw.save(update_fields=[
                    'last_seen_at', 'fetched_at', 'updated_at',
                ])

        return raw

    # ── Parse ────────────────────────────────────────────────────────

    def _try_parse(self, raw: RawPayload, run: SyncRun) -> None:
        """Attempt to parse a raw payload; update status regardless."""
        if raw.parse_status != ParseStatus.PENDING:
            return

        try:
            result = self.parse_and_apply(raw)
            raw.parse_status = ParseStatus.PARSED
            raw.parsed_at = timezone.now()
            raw.parse_error = ''
            raw.save(update_fields=[
                'parse_status', 'parsed_at', 'parse_error', 'updated_at',
            ])
            if result == 'created':
                run.created_count += 1
            elif result == 'updated':
                run.updated_count += 1
        except Exception as exc:
            logger.warning(
                "Parse failed for %s:%s — %s",
                raw.resource_type, raw.remote_id, exc,
            )
            raw.parse_status = ParseStatus.FAILED
            raw.parse_error = str(exc)
            raw.save(update_fields=[
                'parse_status', 'parse_error', 'updated_at',
            ])
            run.error_count += 1

    # ── Domain upsert helper ─────────────────────────────────────────

    def _upsert_order(
        self,
        raw_payload: RawPayload,
        defaults: dict,
    ) -> str:
        """Shared Order upsert. Returns ``'created'`` or ``'updated'``.

        If our_fee is None, it is auto-calculated from FeeRule
        (percent only, flat fee excluded).

        Automatically links the Order to a Listing (and its DropshipProduct)
        by looking up store_listing_id + integration_account.

        OwnedProduct status is updated automatically via post_save signal
        (see apps.inventory.signals).
        """
        from apps.orders.models import Order

        # Auto-calculate fee if not provided by the marketplace API
        if defaults.get('our_fee') is None:
            self._auto_calculate_fee(raw_payload, defaults)

        # Link Order to Listing (and DropshipProduct) if not already set
        if 'listing' not in defaults:
            self._link_listing(raw_payload, defaults)

        order, created = Order.objects.update_or_create(
            integration_account=raw_payload.integration_account,
            store_order_id=raw_payload.remote_id,
            defaults=defaults,
        )

        # Reactive pool check: new order = sale detected
        if created and order.store_listing_id:
            self._notify_pool_on_sale(order)

        return 'created' if created else 'updated'

    @staticmethod
    def _link_listing(raw_payload: RawPayload, defaults: dict) -> None:
        """Resolve Listing (and its DropshipProduct) from store_listing_id.

        Uses the unique (integration_account, store_listing_id) pair to
        find the corresponding Listing. If the listing has a linked
        DropshipProduct, that is also set on the Order defaults.
        """
        store_listing_id = defaults.get('store_listing_id')
        if not store_listing_id or not raw_payload.integration_account:
            return

        from apps.listings.models import Listing

        listing = (
            Listing.objects
            .filter(
                integration_account=raw_payload.integration_account,
                store_listing_id=store_listing_id,
            )
            .select_related('dropship_product')
            .first()
        )
        if not listing:
            return

        defaults['listing'] = listing
        if listing.dropship_product_id:
            defaults['dropship_product'] = listing.dropship_product

    @staticmethod
    def _auto_calculate_fee(raw_payload: RawPayload, defaults: dict) -> None:
        """Calculate our_fee from FeeRule (percent only, no flat fee)."""
        from apps.orders.enums import FeeType
        from apps.orders.fees import calculate_fee, compute_fee_amount

        provider = ''
        if raw_payload.integration_account:
            provider = raw_payload.integration_account.provider
        if not provider:
            return

        sold_at = defaults.get('sold_at')
        ref_date = sold_at.date() if sold_at else None

        rule = calculate_fee(
            marketplace=provider,
            fee_type=FeeType.SALE,
            product_category=defaults.get('product_category') or '',
            game_id=defaults['game'].pk if defaults.get('game') else None,
            ref_date=ref_date,
        )
        if rule:
            defaults['our_fee'] = compute_fee_amount(
                defaults['price'], rule, include_flat=False,
            )

    # ── Pool integration ────────────────────────────────────────────

    @staticmethod
    def _notify_pool_on_sale(order: Any) -> None:
        """If this order's listing has an offer pool, trigger replenish check."""
        try:
            from apps.listings.models import Listing
            listing = Listing.objects.filter(
                store_listing_id=order.store_listing_id,
                integration_account=order.integration_account,
            ).only('id').first()
            if listing:
                from apps.posting.services.pool.checker import notify_sale
                notify_sale(listing.id)
        except Exception:
            logger.debug('pool notify_sale skipped (error or not configured)')

    # ── Utilities ────────────────────────────────────────────────────

    def _validated_remote_id(self, item: dict) -> str:
        remote_id = str(self.extract_remote_id(item) or '').strip()
        if not remote_id:
            raise ValueError(
                f"{self.__class__.__name__} extracted an empty remote_id "
                f"for resource_type={self.resource_type}."
            )
        return remote_id

    @staticmethod
    def _hash_payload(item: Any) -> str:
        serialised = json.dumps(item, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()
