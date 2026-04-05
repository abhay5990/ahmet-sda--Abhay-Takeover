# Sync Order Pipeline — Architecture Research Document

Last updated: 2026-03-28

## Purpose of This Document

This is a research and analysis document for refactoring the order sync pipeline
in a Django-based multi-marketplace e-commerce management system.

The system syncs orders from gaming marketplaces (Eldorado, Gameboost,
PlayerAuctions, with G2G and LZT planned) into a local database.

This document contains:

1. The full current codebase for the sync system
2. Known architectural problems with root cause analysis
3. Business decisions already made by the project owner
4. Design principles that must be preserved
5. Specific questions that need architectural solutions

**Your task:** Analyze the codebase and problems, then propose a concrete
refactored architecture. Every recommendation must include class/method-level
detail — not just "add a hook" but show the hook signature, where it's called,
and how each provider implements it.

---

## System Context

### What this system does

- Fetches orders from multiple gaming marketplace APIs
- Stores raw API responses as staging data (`RawPayload`)
- Parses raw data into canonical `Order` records
- Tracks sync progress via checkpoints for resume capability
- Currently supports 3 providers, 2 more planned

### Provider characteristics

| Provider | Pagination | Enrichment | Sort | Auth |
|----------|-----------|------------|------|------|
| Eldorado | Cursor-based (newest→oldest) | Account details for instant account orders (credentials data) | Cursor-directed | Cognito SRP |
| Gameboost | Page-based (page 1 = newest) | None needed | `-updated_at` | Bearer token |
| PlayerAuctions | Page-based (page 1 = newest) | Per-order detail fetch required (list = summary only) | Default (newest first) | JWT + Cookie |
| G2G (planned) | TBD | TBD | TBD | Multi-token |
| LZT (planned) | TBD | TBD | TBD | API key |

### Tech stack

- Django 5.x, PostgreSQL
- Custom SDK library (`libs/apis_sdk/`) with per-provider clients
- Management commands as runtime interface (no Celery yet)
- SDK returns `ApiResult[T]` (functional error handling, not exceptions)

---

## Current Codebase

### File structure

```
backend/apps/sync/
├── enums.py                              # ResourceType, SyncMode, ParseStatus, etc.
├── models.py                             # RawPayload, SyncCheckpoint, SyncRun
├── admin.py                              # Django admin registration
├── services/
│   ├── base.py                           # BaseSyncService (abstract orchestrator)
│   ├── eldorado/
│   │   ├── service.py                    # EldoradoOrderSyncService
│   │   └── mapper.py                     # Status/category/enrichment mapping
│   ├── gameboost/
│   │   ├── service.py                    # GameboostOrderSyncService
│   │   └── mapper.py                     # Status/category/price mapping
│   └── playerauctions/
│       ├── service.py                    # PlayerAuctionsOrderSyncService
│       └── mapper.py                     # Status/category/price/datetime mapping
└── management/commands/
    └── sync_orders.py                    # CLI entry point

backend/apps/orders/
├── models.py                             # Order model
└── enums.py                              # OrderStatus choices
```

### Source Code

#### `backend/apps/sync/enums.py`

```python
from django.db import models


class ResourceType(models.TextChoices):
    ORDERS = 'orders', 'Orders'
    LISTINGS = 'listings', 'Listings'


class SyncMode(models.TextChoices):
    BACKFILL = 'backfill', 'Backfill'
    INCREMENTAL = 'incremental', 'Incremental'


class ParseStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PARSED = 'parsed', 'Parsed'
    FAILED = 'failed', 'Failed'
    SKIPPED = 'skipped', 'Skipped'


class CheckpointStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    COMPLETED = 'completed', 'Completed'  # backfill finished
    STALE = 'stale', 'Stale'  # needs reset


class SyncRunStatus(models.TextChoices):
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'
```

#### `backend/apps/sync/models.py`

```python
from django.db import models
from django.utils import timezone

from .enums import (
    ResourceType, SyncMode, ParseStatus, CheckpointStatus, SyncRunStatus,
)


class RawPayload(models.Model):
    """Raw provider payload stored before parsing.

    Design: latest-snapshot with upsert keyed on
    (integration_account, resource_type, remote_id).
    """

    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='raw_payloads',
    )
    resource_type = models.CharField(max_length=20, choices=ResourceType.choices)
    remote_id = models.CharField(max_length=255)

    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)

    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    fetched_at = models.DateTimeField()

    parse_status = models.CharField(
        max_length=20, choices=ParseStatus.choices, default=ParseStatus.PENDING,
    )
    parse_error = models.TextField(blank=True)
    parsed_at = models.DateTimeField(null=True, blank=True)

    meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_raw_payloads'
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'resource_type', 'remote_id'],
                name='unique_account_resource_remote',
            ),
        ]
        indexes = [
            models.Index(fields=['resource_type', 'parse_status']),
            models.Index(
                fields=['integration_account', 'resource_type', 'parse_status'],
            ),
            models.Index(fields=['fetched_at']),
        ]
        ordering = ['-fetched_at']

    def __str__(self):
        return f"{self.resource_type}:{self.remote_id} ({self.parse_status})"


class SyncCheckpoint(models.Model):
    """Tracks cursor/resume state for a sync stream.

    One row per (integration_account, resource_type, mode) combination.
    """

    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='sync_checkpoints',
    )
    resource_type = models.CharField(max_length=20, choices=ResourceType.choices)
    mode = models.CharField(max_length=20, choices=SyncMode.choices)

    cursor = models.TextField(blank=True)
    last_seen_remote_id = models.CharField(max_length=255, blank=True)
    last_seen_remote_timestamp = models.DateTimeField(null=True, blank=True)

    last_run_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=CheckpointStatus.choices,
        default=CheckpointStatus.ACTIVE,
    )

    meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_checkpoints'
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'resource_type', 'mode'],
                name='unique_account_resource_mode',
            ),
        ]
        ordering = ['-updated_at']

    def __str__(self):
        return (
            f"{self.integration_account} / {self.resource_type} / {self.mode} "
            f"({self.status})"
        )

    def advance(self, remote_id: str, remote_timestamp=None, cursor: str = ''):
        self.last_seen_remote_id = remote_id
        self.cursor = cursor
        if remote_timestamp:
            self.last_seen_remote_timestamp = remote_timestamp
        self.last_run_at = timezone.now()
        self.save(update_fields=[
            'last_seen_remote_id', 'last_seen_remote_timestamp',
            'cursor', 'last_run_at', 'updated_at',
        ])


class SyncRun(models.Model):
    """Audit log for each sync execution."""

    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount',
        on_delete=models.CASCADE,
        related_name='sync_runs',
    )
    resource_type = models.CharField(max_length=20, choices=ResourceType.choices)
    mode = models.CharField(max_length=20, choices=SyncMode.choices)
    status = models.CharField(
        max_length=20, choices=SyncRunStatus.choices,
        default=SyncRunStatus.RUNNING,
    )

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    processed_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_runs'
        indexes = [
            models.Index(fields=['integration_account', 'resource_type']),
            models.Index(fields=['status']),
            models.Index(fields=['-started_at']),
        ]
        ordering = ['-started_at']

    def __str__(self):
        return (
            f"SyncRun {self.pk} — {self.resource_type}/{self.mode} "
            f"({self.status})"
        )

    def finish(self, status: str, **counters):
        self.status = status
        self.finished_at = timezone.now()
        for key, value in counters.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save(update_fields=[
            'status', 'finished_at', 'updated_at',
            'processed_count', 'created_count', 'updated_count', 'error_count',
        ])
```

#### `backend/apps/sync/services/base.py`

```python
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.sync.enums import (
    CheckpointStatus, ParseStatus, SyncMode, SyncRunStatus,
)
from apps.sync.models import RawPayload, SyncCheckpoint, SyncRun

logger = logging.getLogger(__name__)


class BaseSyncService:
    resource_type: str = ''
    is_ready: bool = True

    # ── Subclass hooks ───────────────────────────────────────────────

    def fetch_page(self, account, checkpoint: SyncCheckpoint) -> tuple[list[dict], str]:
        raise NotImplementedError

    def extract_remote_id(self, item: dict) -> str:
        raise NotImplementedError

    def extract_remote_timestamp(self, item: dict):
        return None

    def is_already_seen(self, item: dict, checkpoint: SyncCheckpoint) -> bool:
        return False

    def parse_and_apply(self, raw_payload: RawPayload) -> None:
        raise NotImplementedError

    # ── Orchestration ────────────────────────────────────────────────

    def run(self, account, mode: str) -> SyncRun:
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

        if '_incremental_page' in checkpoint.meta:
            checkpoint.meta.pop('_incremental_page', None)
            checkpoint.save(update_fields=['meta', 'updated_at'])

        run = SyncRun.objects.create(
            integration_account=account,
            resource_type=self.resource_type,
            mode=mode,
        )

        try:
            exhausted = self._fetch_loop(account, checkpoint, run)
            if mode == SyncMode.BACKFILL and exhausted:
                checkpoint.status = CheckpointStatus.COMPLETED
                checkpoint.save(update_fields=['status', 'updated_at'])
            run.finish(SyncRunStatus.COMPLETED)
        except Exception:
            logger.exception("SyncRun %s failed", run.pk)
            run.finish(SyncRunStatus.FAILED)
            raise

        return run

    # ── Internals ────────────────────────────────────────────────────

    def _get_or_create_checkpoint(self, account, mode: str) -> SyncCheckpoint:
        checkpoint, _ = SyncCheckpoint.objects.get_or_create(
            integration_account=account,
            resource_type=self.resource_type,
            mode=mode,
            defaults={'status': CheckpointStatus.ACTIVE},
        )
        return checkpoint

    def _fetch_loop(self, account, checkpoint: SyncCheckpoint, run: SyncRun) -> bool:
        fetched_any = False
        caught_up = False

        while True:
            items, next_cursor = self.fetch_page(account, checkpoint)
            if not items:
                break

            fetched_any = True

            with transaction.atomic():
                last_remote_id = None
                last_remote_ts = None

                for item in items:
                    if self.is_already_seen(item, checkpoint):
                        caught_up = True
                        break

                    remote_id = self._validated_remote_id(item)
                    remote_ts = self.extract_remote_timestamp(item)
                    raw = self._ingest_raw(account, remote_id, item)
                    self._try_parse(raw, run)
                    last_remote_id = remote_id
                    last_remote_ts = remote_ts
                    run.processed_count += 1

                if last_remote_id:
                    checkpoint.advance(
                        remote_id=last_remote_id,
                        remote_timestamp=last_remote_ts,
                        cursor=next_cursor,
                    )

                run.save(update_fields=[
                    'processed_count', 'created_count',
                    'updated_count', 'error_count', 'updated_at',
                ])

            if caught_up or not next_cursor:
                break

        return fetched_any and not next_cursor

    def _ingest_raw(self, account, remote_id: str, item: dict) -> RawPayload:
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

    def _try_parse(self, raw: RawPayload, run: SyncRun):
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

    def _validated_remote_id(self, item: dict) -> str:
        remote_id = str(self.extract_remote_id(item) or '').strip()
        if not remote_id:
            raise ValueError(
                f"{self.__class__.__name__} extracted an empty remote_id"
            )
        return remote_id

    @staticmethod
    def _hash_payload(item: Any) -> str:
        serialised = json.dumps(item, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()
```

#### `backend/apps/sync/services/eldorado/service.py`

```python
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from apps.orders.models import Order
from apps.sync.enums import ParseStatus, ResourceType
from apps.sync.models import RawPayload, SyncCheckpoint, SyncRun
from apps.sync.services.base import BaseSyncService
from . import mapper

logger = logging.getLogger(__name__)


class EldoradoOrderSyncService(BaseSyncService):
    resource_type = ResourceType.ORDERS

    def __init__(self, provider, client):
        self.provider = provider
        self.client = client

    DIRECTION = 'newest_first'

    _DIRECTION_CONFIG = {
        'newest_first': {
            'initial_cursor': '9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999',
            'page_direction': 'Next',
            'next_cursor_field': 'nextPageCursor',
        },
        'oldest_first': {
            'initial_cursor': '0000-00-00 00:00:00.000000000000000-0000-0000-0000-000000000000',
            'page_direction': 'Previous',
            'next_cursor_field': 'previousPageCursor',
        },
    }

    # ── Subclass hooks ───────────────────────────────────────────────

    def fetch_page(self, account, checkpoint: SyncCheckpoint) -> tuple[list[dict], str]:
        cfg = self._DIRECTION_CONFIG[self.DIRECTION]
        cursor_value = checkpoint.cursor or cfg['initial_cursor']

        params = {
            'cursorValue': cursor_value,
            'pageSize': '20',
            'pageDirection': cfg['page_direction'],
            'isAscendingDateOrder': 'false',
            'ignorePendingReviewOrders': 'true',
            'displayFilter': 'DisplaySellingOrders',
            'orderGroup': 'Regular',
        }

        result = self.provider.fetch_orders(self.client, params=params)

        if not result.ok or result.data is None:
            return [], ''

        page = result.data
        items = [order.model_dump() for order in page.results]
        next_cursor = getattr(page, cfg['next_cursor_field'], None) or ''

        return items, next_cursor

    def extract_remote_id(self, item: dict) -> str:
        return str(item.get('id') or '').strip()

    def extract_remote_timestamp(self, item: dict):
        raw_ts = item.get('createdDate')
        if not raw_ts:
            return None
        try:
            return datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        payload = raw_payload.payload
        meta = raw_payload.meta or {}
        offer = payload.get('orderOfferDetails') or {}

        is_instant_account = (
            offer.get('category') == 'Account'
            and offer.get('guaranteedDeliveryTime') == 'Instant'
        )
        if is_instant_account and meta.get('enrichment') == 'failed':
            raw_payload.parse_status = ParseStatus.SKIPPED
            raw_payload.parse_error = 'Enrichment failed — account details missing'
            raw_payload.save(
                update_fields=['parse_status', 'parse_error', 'updated_at'],
            )
            return None

        defaults = {
            'is_instant': offer.get('guaranteedDeliveryTime') == 'Instant',
            'product_category': mapper.map_category(offer.get('category')),
            'status': mapper.map_status(payload),
            'price': Decimal(
                str(payload.get('totalPrice', {}).get('amount', 0)),
            ),
            'currency': payload.get('totalPrice', {}).get('currency', 'USD'),
            'our_fee': self._extract_fee(payload),
            'sold_at': self.extract_remote_timestamp(payload),
            'store_listing_id': payload.get('offerId') or '',
            'raw_data': payload,
        }

        order, created = Order.objects.update_or_create(
            integration_account=raw_payload.integration_account,
            store_order_id=raw_payload.remote_id,
            defaults=defaults,
        )

        return 'created' if created else 'updated'

    # ── Parse helpers ────────────────────────────────────────────────

    @staticmethod
    def _extract_fee(payload: dict) -> Decimal | None:
        fees = (payload.get('sellerPayments') or {}).get('sellerFees')
        if fees and fees.get('amount') is not None:
            return Decimal(str(fees['amount']))
        return None

    # ── Enrichment ───────────────────────────────────────────────────

    def _enrich_order(self, item: dict) -> tuple[dict, dict]:
        order_id = item.get('id', '')
        try:
            result = self.provider.fetch_order_account_details(
                self.client, order_id,
            )

            if not result.ok or result.data is None:
                error_msg = ''
                if hasattr(result, 'error') and result.error:
                    error_msg = getattr(result.error, 'message', str(result.error))
                return item, {
                    'enrichment': 'failed',
                    'enrichment_error': error_msg or 'empty response',
                }

            if hasattr(result.data, 'model_dump'):
                item['accountDetails'] = result.data.model_dump()
            else:
                item['accountDetails'] = result.data

            return item, {'enrichment': 'completed'}

        except Exception as exc:
            logger.warning(
                "Enrichment failed for order %s: %s", order_id, exc,
            )
            return item, {
                'enrichment': 'failed',
                'enrichment_error': str(exc),
            }

    # ── Fetch loop override ──────────────────────────────────────────

    def _fetch_loop(
        self, account, checkpoint: SyncCheckpoint, run: SyncRun,
    ) -> bool:
        fetched_any = False
        enrichment_attempted = 0
        enrichment_failed = 0

        while True:
            items, next_cursor = self.fetch_page(account, checkpoint)
            if not items:
                break

            fetched_any = True

            with transaction.atomic():
                last_remote_id = None
                last_remote_ts = None

                for item in items:
                    remote_id = self._validated_remote_id(item)
                    remote_ts = self.extract_remote_timestamp(item)

                    # Enrichment
                    enrich_meta = {}
                    if mapper.needs_enrichment(item):
                        enrichment_attempted += 1
                        item, enrich_meta = self._enrich_order(item)
                        if enrich_meta.get('enrichment') == 'failed':
                            enrichment_failed += 1
                    else:
                        enrich_meta = {'enrichment': 'not_required'}

                    # Ingest raw payload with enrichment meta
                    raw = self._ingest_raw(account, remote_id, item)
                    raw.meta = {**raw.meta, **enrich_meta}
                    raw.save(update_fields=['meta', 'updated_at'])

                    self._try_parse(raw, run)

                    last_remote_id = remote_id
                    last_remote_ts = remote_ts
                    run.processed_count += 1

                if last_remote_id:
                    checkpoint.advance(
                        remote_id=last_remote_id,
                        remote_timestamp=last_remote_ts,
                        cursor=next_cursor,
                    )

                run.meta = {
                    **run.meta,
                    'enrichment_attempted_count': enrichment_attempted,
                    'enrichment_failed_count': enrichment_failed,
                }
                run.save(update_fields=[
                    'processed_count', 'created_count',
                    'updated_count', 'error_count',
                    'meta', 'updated_at',
                ])

            if not next_cursor:
                break

        return fetched_any and not next_cursor
```

#### `backend/apps/sync/services/eldorado/mapper.py`

```python
from __future__ import annotations

from apps.orders.enums import OrderStatus
from core.enums import ProductCategory

ELDORADO_STATUS_MAP = {
    'Initialized': OrderStatus.PENDING,
    'Paid': OrderStatus.PENDING,
    'Delivered': OrderStatus.DELIVERED,
    'Received': OrderStatus.DELIVERED,
    'Completed': OrderStatus.COMPLETED,
    'Cancelled': OrderStatus.CANCELLED,
    'Refunded': OrderStatus.REFUNDED,
}


def map_status(payload: dict) -> str:
    state = (payload.get('state') or {}).get('state', '')
    dispute = payload.get('dispute') or {}
    if dispute.get('disputedByUserRole') is not None:
        return OrderStatus.DISPUTED
    return ELDORADO_STATUS_MAP.get(state, OrderStatus.PENDING)


def map_category(category: str | None) -> str:
    if category == 'Currency':
        return ProductCategory.CURRENCY
    if category == 'Account':
        return ProductCategory.ACCOUNTS
    return ProductCategory.ITEMS


def needs_enrichment(item: dict) -> bool:
    offer = item.get('orderOfferDetails') or {}
    return (
        offer.get('category') == 'Account'
        and offer.get('guaranteedDeliveryTime') == 'Instant'
    )
```

#### `backend/apps/sync/services/gameboost/service.py`

```python
from __future__ import annotations

import logging
from decimal import Decimal

from apps.orders.models import Order
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from . import mapper

logger = logging.getLogger(__name__)


class GameboostOrderSyncService(BaseSyncService):
    resource_type = ResourceType.ORDERS
    DEFAULT_PAGE_SIZE = 15
    DEFAULT_SORT = '-updated_at'

    def __init__(self, provider, client):
        self.provider = provider
        self.client = client

    def is_already_seen(self, item: dict, checkpoint: SyncCheckpoint) -> bool:
        if checkpoint.mode != SyncMode.INCREMENTAL:
            return False
        if not checkpoint.last_seen_remote_id:
            return False
        remote_id = str(item.get('id') or '').strip()
        return remote_id == checkpoint.last_seen_remote_id

    def fetch_page(
        self, account, checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        if checkpoint.mode == SyncMode.INCREMENTAL:
            page = checkpoint.meta.get('_incremental_page', 1)
        else:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1

        result = self.provider.fetch_orders(
            self.client,
            params={
                'page': page,
                'per_page': self.DEFAULT_PAGE_SIZE,
                'sort': self.DEFAULT_SORT,
            },
        )

        if not result.ok:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"Gameboost API error on page {page}: {error_msg}"
            )

        items = []
        for order in (result.data or []):
            if hasattr(order, 'model_dump'):
                items.append(order.model_dump())
            elif isinstance(order, dict):
                items.append(order)
            else:
                items.append(dict(order))

        if not items:
            return [], ''

        pagination = result.meta.get('pagination', {})
        current_page = pagination.get('current_page', page)
        last_page = pagination.get('last_page', current_page)

        if current_page < last_page:
            next_cursor = str(current_page + 1)
        else:
            next_cursor = ''

        if checkpoint.mode == SyncMode.INCREMENTAL and next_cursor:
            checkpoint.meta = {
                **checkpoint.meta,
                '_incremental_page': current_page + 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

        return items, next_cursor

    def extract_remote_id(self, item: dict) -> str:
        return str(item.get('id') or '').strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_unix_timestamp(
            item.get('purchased_at') or item.get('created_at'),
        )

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        payload = raw_payload.payload
        price_value, currency = mapper.extract_price_usd(payload)

        defaults = {
            'is_instant': not payload.get('is_manual_delivery', False),
            'product_category': mapper.map_category(payload),
            'status': mapper.map_status(payload.get('status', '')),
            'price': Decimal(str(price_value)),
            'currency': currency,
            'our_fee': None,
            'sold_at': mapper.parse_unix_timestamp(
                payload.get('purchased_at') or payload.get('created_at'),
            ),
            'store_listing_id': mapper.extract_listing_id(payload),
            'raw_data': payload,
        }

        order, created = Order.objects.update_or_create(
            integration_account=raw_payload.integration_account,
            store_order_id=raw_payload.remote_id,
            defaults=defaults,
        )

        return 'created' if created else 'updated'
```

#### `backend/apps/sync/services/gameboost/mapper.py`

```python
from __future__ import annotations

from datetime import datetime, timezone

from apps.orders.enums import OrderStatus
from core.enums import ProductCategory

GAMEBOOST_STATUS_MAP = {
    'new': OrderStatus.PENDING,
    'in_delivery': OrderStatus.PENDING,
    'delivered': OrderStatus.DELIVERED,
    'completed': OrderStatus.COMPLETED,
    'refunded': OrderStatus.REFUNDED,
    'cancelled': OrderStatus.CANCELLED,
    'disputed': OrderStatus.DISPUTED,
}


def map_status(status_str: str) -> str:
    return GAMEBOOST_STATUS_MAP.get(status_str.lower(), OrderStatus.PENDING)


def map_category(item: dict) -> str:
    if item.get('currency_offer_id'):
        return ProductCategory.CURRENCY
    return ProductCategory.ACCOUNTS


def extract_price_usd(item: dict) -> tuple[float, str]:
    price_usd = item.get('price_usd')
    if isinstance(price_usd, dict) and price_usd.get('value') is not None:
        return float(price_usd['value']), 'USD'

    price_obj = item.get('price')
    if isinstance(price_obj, dict) and price_obj.get('value') is not None:
        currency = 'EUR'
        cur = price_obj.get('currency')
        if isinstance(cur, dict) and cur.get('code'):
            currency = cur['code']
        return float(price_obj['value']), currency

    price_eur = item.get('price_eur')
    if isinstance(price_eur, dict) and price_eur.get('value') is not None:
        return float(price_eur['value']), 'EUR'

    return 0.0, 'USD'


def parse_unix_timestamp(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def extract_listing_id(item: dict) -> str:
    offer_id = item.get('account_offer_id') or item.get('currency_offer_id')
    return str(offer_id) if offer_id else ''
```

#### `backend/apps/sync/services/playerauctions/service.py`

```python
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction

from apps.orders.models import Order
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint, SyncRun
from apps.sync.services.base import BaseSyncService
from . import mapper

logger = logging.getLogger(__name__)


class PlayerAuctionsOrderSyncService(BaseSyncService):
    resource_type = ResourceType.ORDERS

    DEFAULT_ORDER_STATUS = 'All'
    DEFAULT_PRODUCT_TYPE = 'Accounts'
    DEFAULT_PAGE_SIZE = 50

    SKIP_STATUSES = frozenset({
        'Pending Payment',
        'Offer Unavailable',
        'Buyer Cancelled',
        'Order Unavailable',
    })

    def __init__(self, provider, client, *, order_status=None, product_type=None):
        self.provider = provider
        self.client = client
        self.order_status = order_status or self.DEFAULT_ORDER_STATUS
        self.product_type = product_type or self.DEFAULT_PRODUCT_TYPE

    def fetch_page(
        self, account, checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        if checkpoint.mode == SyncMode.INCREMENTAL:
            page = checkpoint.meta.get('_incremental_page', 1)
        else:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1

        result = self.provider.fetch_orders(
            self.client,
            page=page,
            page_size=self.DEFAULT_PAGE_SIZE,
            order_status=self.order_status,
            product_type=self.product_type,
        )

        if not result.ok:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"PlayerAuctions API error on page {page}: {error_msg}"
            )

        items = []
        for order in (result.data or []):
            if hasattr(order, 'model_dump'):
                items.append(order.model_dump())
            elif isinstance(order, dict):
                items.append(order)
            else:
                items.append(dict(order))

        if not items:
            return [], ''

        total_count = result.meta.get('total_count', 0)
        if isinstance(total_count, str):
            total_count = int(total_count)

        total_pages = (
            (total_count + self.DEFAULT_PAGE_SIZE - 1) // self.DEFAULT_PAGE_SIZE
            if total_count else 0
        )

        if page < total_pages:
            next_cursor = str(page + 1)
        else:
            next_cursor = ''

        if checkpoint.mode == SyncMode.INCREMENTAL and next_cursor:
            checkpoint.meta = {
                **checkpoint.meta,
                '_incremental_page': page + 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

        return items, next_cursor

    def is_already_seen(self, item: dict, checkpoint: SyncCheckpoint) -> bool:
        if checkpoint.mode != SyncMode.INCREMENTAL:
            return False
        if not checkpoint.last_seen_remote_id:
            return False
        remote_id = str(
            item.get('order_id') or item.get('orderId') or item.get('id') or '',
        ).strip()
        return remote_id == checkpoint.last_seen_remote_id

    def extract_remote_id(self, item: dict) -> str:
        return str(
            item.get('order_id') or item.get('orderId') or item.get('id') or '',
        ).strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_pa_datetime(
            item.get('create_time') or item.get('createTime') or '',
        )

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        payload = raw_payload.payload

        status_str = mapper.extract_status_from_detail(payload)
        if not status_str:
            status_str = payload.get('status') or ''

        order_info = (
            payload.get('order_info') or payload.get('orderInfo') or {}
        )
        price_str = order_info.get('price') or payload.get('price') or ''
        price_value, currency = mapper.parse_price_string(price_str)

        create_time = (
            payload.get('create_time') or payload.get('createTime') or ''
        )
        sold_at = mapper.parse_pa_datetime(create_time)

        product_type = (
            payload.get('product_type') or payload.get('productType') or ''
        )
        product_category = mapper.map_category(product_type)

        listing_id = mapper.extract_listing_id_from_detail(payload)

        defaults = {
            'is_instant': mapper.extract_is_instant(payload),
            'product_category': product_category,
            'status': mapper.map_status(status_str),
            'price': Decimal(str(price_value)),
            'currency': currency,
            'our_fee': None,
            'sold_at': sold_at,
            'store_listing_id': listing_id,
            'raw_data': payload,
        }

        order, created = Order.objects.update_or_create(
            integration_account=raw_payload.integration_account,
            store_order_id=raw_payload.remote_id,
            defaults=defaults,
        )

        return 'created' if created else 'updated'

    # ── Fetch loop override (detail enrichment) ───────────────────────

    def _fetch_loop(
        self, account, checkpoint: SyncCheckpoint, run: SyncRun,
    ) -> bool:
        fetched_any = False
        caught_up = False
        detail_attempted = 0
        detail_failed = 0

        while True:
            items, next_cursor = self.fetch_page(account, checkpoint)
            if not items:
                break

            fetched_any = True

            with transaction.atomic():
                last_remote_id = None
                last_remote_ts = None

                for summary in items:
                    if self.is_already_seen(summary, checkpoint):
                        caught_up = True
                        break

                    remote_id = self._validated_remote_id(summary)
                    remote_ts = self.extract_remote_timestamp(summary)

                    order_status = summary.get('status') or ''
                    if order_status in self.SKIP_STATUSES:
                        run.processed_count += 1
                        last_remote_id = remote_id
                        last_remote_ts = remote_ts
                        continue

                    detail_attempted += 1
                    merged = self._fetch_and_merge_detail(summary, remote_id)

                    if merged is None:
                        detail_failed += 1
                        run.processed_count += 1
                        run.error_count += 1
                        # NOTE: raw payload is NOT written here — this is a
                        # known gap addressed in the design document
                        continue

                    raw = self._ingest_raw(account, remote_id, merged)
                    self._try_parse(raw, run)

                    last_remote_id = remote_id
                    last_remote_ts = remote_ts
                    run.processed_count += 1

                if caught_up:
                    if last_remote_id:
                        checkpoint.advance(
                            remote_id=last_remote_id,
                            remote_timestamp=last_remote_ts,
                            cursor=next_cursor,
                        )
                else:
                    effective_remote_id = last_remote_id
                    effective_remote_ts = last_remote_ts
                    if not effective_remote_id and items:
                        fallback = items[-1]
                        effective_remote_id = self._validated_remote_id(
                            fallback,
                        )
                        effective_remote_ts = self.extract_remote_timestamp(
                            fallback,
                        )

                    if effective_remote_id:
                        checkpoint.advance(
                            remote_id=effective_remote_id,
                            remote_timestamp=effective_remote_ts,
                            cursor=next_cursor,
                        )

                run.meta = {
                    **run.meta,
                    'detail_attempted_count': detail_attempted,
                    'detail_failed_count': detail_failed,
                }
                run.save(update_fields=[
                    'processed_count', 'created_count',
                    'updated_count', 'error_count',
                    'meta', 'updated_at',
                ])

            if caught_up or not next_cursor:
                break

        return fetched_any and not next_cursor

    def _fetch_and_merge_detail(
        self, summary: dict, remote_id: str,
    ) -> dict | None:
        try:
            result = self.provider.fetch_order_details(
                self.client, remote_id,
            )
            if not result.ok:
                return None

            detail_data = result.data
            if hasattr(detail_data, 'model_dump'):
                detail_dict = detail_data.model_dump()
            elif isinstance(detail_data, dict):
                detail_dict = detail_data
            else:
                detail_dict = dict(detail_data)

            merged = {**summary, **detail_dict}
            for key in (
                'create_time', 'createTime', 'product_type', 'productType',
            ):
                if key in summary and summary[key]:
                    merged[key] = summary[key]

            return merged

        except Exception as exc:
            logger.warning(
                "PA detail fetch exception for order %s: %s",
                remote_id, exc,
            )
            return None
```

#### `backend/apps/sync/services/playerauctions/mapper.py`

```python
from __future__ import annotations

import re
from datetime import datetime, timezone

from apps.orders.enums import OrderStatus
from core.enums import ProductCategory

PA_STATUS_MAP = {
    'pending payment': OrderStatus.PENDING,
    'payment received': OrderStatus.PENDING,
    'order processing': OrderStatus.PENDING,
    'delivery in progress': OrderStatus.PENDING,
    'delivery fully completed': OrderStatus.COMPLETED,
    'completed': OrderStatus.COMPLETED,
    'cancelled': OrderStatus.CANCELLED,
    'refunded': OrderStatus.REFUNDED,
    'disputed': OrderStatus.DISPUTED,
    'disputed delivery not completed': OrderStatus.DISPUTED,
    'disputed delivery completed': OrderStatus.DISPUTED,
}


def map_status(status_str: str) -> str:
    if not status_str:
        return OrderStatus.PENDING
    return PA_STATUS_MAP.get(status_str.strip().lower(), OrderStatus.PENDING)


def extract_status_from_detail(detail: dict) -> str:
    status_obj = detail.get('status')
    if isinstance(status_obj, dict):
        return status_obj.get('current') or status_obj.get('orderStatus') or ''
    if isinstance(status_obj, str):
        return status_obj
    return ''


PA_CATEGORY_MAP = {
    'game accounts': ProductCategory.ACCOUNTS,
    'accounts': ProductCategory.ACCOUNTS,
    'items': ProductCategory.ITEMS,
    'currency': ProductCategory.CURRENCY,
    'coins': ProductCategory.CURRENCY,
    'gold': ProductCategory.CURRENCY,
}


def map_category(product_type: str) -> str:
    if not product_type:
        return ProductCategory.ACCOUNTS
    return PA_CATEGORY_MAP.get(
        product_type.strip().lower(), ProductCategory.ACCOUNTS,
    )


_PRICE_RE = re.compile(r'[\$€£]?\s*([\d,]+\.?\d*)')


def parse_price_string(price_str: str) -> tuple[float, str]:
    if not price_str:
        return 0.0, 'USD'

    currency = 'USD'
    if '€' in price_str:
        currency = 'EUR'
    elif '£' in price_str:
        currency = 'GBP'

    match = _PRICE_RE.search(price_str)
    if match:
        value_str = match.group(1).replace(',', '')
        try:
            return float(value_str), currency
        except ValueError:
            pass

    return 0.0, currency


_PA_DATETIME_FORMATS = [
    '%b-%d-%Y %I:%M:%S %p',
    '%m/%d/%Y %I:%M %p',
    '%m/%d/%Y %I:%M:%S %p',
    '%m/%d/%Y %H:%M',
    '%Y-%m-%dT%H:%M:%S',
]

_TZ_TAG_RE = re.compile(r'\([A-Z]{2,5}\)\s*$')


def parse_pa_datetime(dt_str: str) -> datetime | None:
    if not dt_str:
        return None

    dt_str = _TZ_TAG_RE.sub('', dt_str.strip()).strip()

    for fmt in _PA_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def extract_is_instant(detail: dict) -> bool:
    order_info = detail.get('order_info') or detail.get('orderInfo') or {}
    offer_info = (
        order_info.get('offerInfo') or order_info.get('offer_info') or {}
    )
    unit = offer_info.get('unit') or ''
    return unit.strip().lower() == 'instant'


def extract_listing_id_from_detail(detail: dict) -> str:
    order_info = detail.get('order_info') or detail.get('orderInfo') or {}

    offer_id = order_info.get('offerId') or order_info.get('offer_id') or ''
    if offer_id:
        return str(offer_id)

    offer_info = (
        order_info.get('offerInfo') or order_info.get('offer_info') or {}
    )
    link = offer_info.get('link') or ''
    if link:
        parts = link.rstrip('/').split('/')
        if parts:
            return parts[-1]

    return ''
```

#### `backend/apps/sync/management/commands/sync_orders.py`

```python
from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_provider
from apps.sync.enums import SyncMode
from apps.sync.services.eldorado.service import EldoradoOrderSyncService
from apps.sync.services.gameboost.service import GameboostOrderSyncService
from apps.sync.services.playerauctions.service import (
    PlayerAuctionsOrderSyncService,
)

_SERVICE_MAP = {
    'eldorado': EldoradoOrderSyncService,
    'gameboost': GameboostOrderSyncService,
    'playerauctions': PlayerAuctionsOrderSyncService,
}


class Command(BaseCommand):
    help = 'Sync orders from a provider into the local database.'

    def add_arguments(self, parser):
        parser.add_argument(
            'account', type=str,
            help='IntegrationAccount slug',
        )
        parser.add_argument(
            '--mode', type=str,
            choices=[m.value for m in SyncMode],
            default=SyncMode.INCREMENTAL,
        )
        parser.add_argument(
            '--dry-run', action='store_true',
        )

    def handle(self, *args, **options):
        slug = options['account']
        mode = options['mode']
        dry_run = options['dry_run']

        try:
            account = IntegrationAccount.objects.select_related(
                'credential',
            ).get(slug=slug, is_active=True)
        except IntegrationAccount.DoesNotExist:
            raise CommandError(
                f'Active IntegrationAccount with slug "{slug}" not found.'
            )

        if (
            not hasattr(account, 'credential')
            or not account.credential.is_active
        ):
            raise CommandError(
                f'Account "{slug}" has no active credentials.'
            )

        service_class = _SERVICE_MAP.get(account.provider)
        if service_class is None:
            raise CommandError(
                f'No sync service for provider "{account.provider}".'
            )

        provider = get_provider(account.provider)

        try:
            client = provider.build_client(account.credential)
        except Exception as exc:
            raise CommandError(
                f'Failed to build client for "{slug}": {exc}'
            )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS("Dry run — setup validated OK."),
            )
            return

        service = service_class(provider, client)
        run = service.run(account, mode=mode)

        if run is None:
            self.stdout.write(self.style.WARNING(
                "Backfill already completed. Reset checkpoint to re-run."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"SyncRun {run.pk}: status={run.status} "
            f"processed={run.processed_count} created={run.created_count} "
            f"updated={run.updated_count} errors={run.error_count}"
        ))

        enrichment_failed = run.meta.get('enrichment_failed_count', 0)
        if enrichment_failed:
            self.stdout.write(self.style.WARNING(
                f"Enrichment failures: {enrichment_failed}"
            ))

        detail_failed = run.meta.get('detail_failed_count', 0)
        if detail_failed:
            self.stdout.write(self.style.WARNING(
                f"Detail fetch failures: {detail_failed}"
            ))
```

#### `backend/apps/orders/models.py`

```python
from django.db import models

from core.enums import ProductCategory
from .enums import OrderStatus


class Order(models.Model):
    is_instant = models.BooleanField(default=True)
    product_category = models.CharField(
        max_length=20, choices=ProductCategory.choices,
        default=ProductCategory.ACCOUNTS,
    )
    owned_product = models.ForeignKey(
        'inventory.OwnedProduct', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )
    dropship_product = models.ForeignKey(
        'inventory.DropshipProduct', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )
    listing = models.ForeignKey(
        'listings.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )
    integration_account = models.ForeignKey(
        'integrations.IntegrationAccount', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )
    store_order_id = models.CharField(max_length=255)
    store_listing_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING,
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    our_fee = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    sold_at = models.DateTimeField(null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['integration_account', 'store_order_id'],
                name='unique_account_order',
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['store_order_id']),
        ]

    def __str__(self):
        return f"Order {self.store_order_id} ({self.get_status_display()})"
```

#### `backend/apps/orders/enums.py`

```python
from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DELIVERED = 'delivered', 'Delivered'
    COMPLETED = 'completed', 'Completed'
    REFUNDED = 'refunded', 'Refunded'
    DISPUTED = 'disputed', 'Disputed'
    CANCELLED = 'cancelled', 'Cancelled'
```

---

## Known Architectural Problems

### Problem 1: `_fetch_loop` Override Duplication (DRY Violation)

`BaseSyncService._fetch_loop` defines the core page→ingest→parse→checkpoint
loop. But 2 of 3 providers (Eldorado, PlayerAuctions) completely override it.

The overrides copy ~80% of the base logic and add provider-specific behavior:

- **Eldorado** adds: per-item enrichment call, enrichment failure tracking,
  meta merge into RawPayload
- **PlayerAuctions** adds: per-item detail fetch, skip-status filtering,
  fallback checkpoint on all-details-failed pages, detail failure tracking

**Impact:** A bug fix or improvement to the base `_fetch_loop` does NOT
propagate to Eldorado or PlayerAuctions. Three copies of the same checkpoint
and transaction logic must be maintained independently.

### Problem 2: Incremental Sync Is Broken

Backfill and incremental use **separate checkpoint rows** (keyed on `mode`).

After backfill completes:
- Backfill checkpoint: `last_seen_remote_id` populated, `status=COMPLETED`
- Incremental checkpoint: does not exist yet

First incremental run:
- Creates a new checkpoint with empty `last_seen_remote_id`
- `is_already_seen` checks `last_seen_remote_id` → empty → always False
- Result: **full re-scan** identical to backfill (wastes API calls, no harm
  to data due to upsert, but defeats the purpose of incremental)

**Eldorado is worse:** It has no `is_already_seen` implementation at all. The
default returns False. Incremental mode behaves identically to backfill every
time — paginating through ALL orders from newest to oldest with no stop
condition.

**Gameboost sort risk:** Sorts by `-updated_at`. If an old order gets updated,
it moves to page 1. Page-based pagination with shifting sort order can cause
items to be skipped between pages.

### Problem 3: Ingest and Parse Are Coupled

Raw persistence and domain parse happen in the same loop iteration. There is
no way to:

- Run ingest without parsing (`--ingest-only`)
- Run parse without fetching (`--process-only`)
- Replay failed parses without hitting remote APIs

### Problem 4: Failed Parse Is Never Retried

When parse fails:
1. `parse_status` is set to `FAILED`
2. On next sync, same item is re-fetched from API
3. `_ingest_raw` finds existing row, hash unchanged → keeps `FAILED` status
4. `_try_parse` checks: `parse_status != PENDING` → returns immediately
5. **Parse is never retried** unless the remote payload changes

This contradicts the intended design where `RawPayload` serves as a durable
staging layer for local replay.

### Problem 5: PlayerAuctions Drops Data on Detail Failure

When `_fetch_and_merge_detail` returns None, the loop calls `continue` without
writing anything to `RawPayload`. The summary data is lost entirely.

### Problem 6: Eldorado Enrichment Failure Handling

Currently: enrichment fails → raw is saved with `meta.enrichment=failed` →
`parse_and_apply` sets `parse_status=SKIPPED`. The order is ingested but never
parsed into the Order table.

### Problem 7: `parse_and_apply` Pattern Repetition

All three providers follow the same pattern:
1. Extract fields from payload using mapper functions
2. Build a `defaults` dict
3. Call `Order.objects.update_or_create(...)`
4. Return `'created'` or `'updated'`

The field extraction differs, but the upsert pattern is identical.

### Problem 8: No Reparse Command

There is no management command to reprocess failed or pending raw payloads
without hitting remote APIs.

---

## Business Decisions (Already Made)

These decisions are final and must not be changed by the proposed architecture:

### BD-1: PlayerAuctions — Do NOT persist summary-only raw

If detail fetch fails for a PlayerAuctions order, do NOT write the summary to
`RawPayload`. Skip the item entirely. Rationale: summary data alone is
incomplete and not useful for domain processing. The order will be picked up on
the next sync run when the detail endpoint is available.

### BD-2: Eldorado — Enrichment failure must stop the sync

If enrichment fails for an instant account order (category=Account,
guaranteedDeliveryTime=Instant), the sync run should raise an error and stop.
Rationale: enrichment contains account credentials (login/password). Without
credentials, the order cannot be fulfilled. This is a critical business
failure, not a soft skip.

**Important context:** Enrichment is only required for instant account orders.
Currency orders, item orders, and non-instant account orders do NOT need
enrichment and should be processed normally regardless.

### BD-3: Reprocess defaults to `failed` only

The `reprocess_raw_payloads` command should default to re-processing `failed`
rows only. `pending` rows are handled by the normal sync flow.

### BD-4: RawPayload is the staging layer

`RawPayload` is the authoritative staging table. Only complete, validated
payloads should be written to it. The checkpoint advances after raw
persistence. Parse failures are recoverable locally.

### BD-5: No partial raw payloads

Since BD-1 says "don't write incomplete PA data" and BD-2 says "stop on
Eldorado enrichment failure", the `completeness=partial` concept from the
earlier design note is no longer needed. Every row in `RawPayload` should
represent a complete, processable payload.

---

## Design Principles (Must Be Preserved)

### DP-1: Raw First, Parse Second

Remote API calls are expensive. Once data is fetched and validated as complete,
persist it immediately. Parse failures must not require re-fetching.

### DP-2: Checkpoint Tracks Ingest, Not Parse

`SyncCheckpoint` means "we have staged everything up to this position."
It does NOT mean "everything was parsed successfully."

### DP-3: Ingest and Process Are Separable Phases

Even when run together, these should be logically distinct. The system should
support `--ingest-only` and `--process-only` modes.

### DP-4: No Over-Engineering

- No Celery, no async workers, no event sourcing
- Management commands remain the runtime interface
- `RawPayload` stays as latest-snapshot, not append-only log
- No premature abstraction for hypothetical future providers

### DP-5: Base Owns the Loop

Provider services should NOT override `_fetch_loop`. All loop, checkpoint, and
transaction logic lives in the base. Providers customize behavior through
well-defined hooks only.

### DP-6: Same Pattern for Future Resources

The architecture must naturally extend to `listings` and `offers` sync without
structural changes — only new provider service subclasses and mappers.

---

## Questions for Analysis

Please analyze the codebase above and propose a concrete refactored
architecture that solves the identified problems while respecting the business
decisions and design principles.

### Q1: Base Service Hook Design

The current `_fetch_loop` is overridden by 2 of 3 providers. Design a hook
system for `BaseSyncService` that eliminates all overrides while supporting:

- Eldorado: per-item enrichment (only for instant account orders), enrichment
  failure raises and stops the run
- PlayerAuctions: per-item detail fetch, skip certain statuses, detail failure
  skips the item entirely (no raw write)
- Gameboost: no per-item processing needed (simplest case)
- Future providers with unknown requirements

Show the exact hook signatures, where they're called in the loop, and how each
of the 3 providers implements them.

### Q2: Ingest/Process Phase Separation

How should `BaseSyncService` be restructured to cleanly separate ingest
(fetch+persist raw) from process (parse+apply to domain)?

Consider:
- Both phases run by default in `sync_orders`
- `--ingest-only` and `--process-only` flags
- `reprocess_raw_payloads` command uses only the process phase
- The process phase needs to know which provider's `parse_and_apply` to call

### Q3: Incremental Sync Fix

How should incremental mode work correctly? Address:

- First incremental after backfill: how to seed the checkpoint
- Eldorado (cursor-based): how to implement stop condition
- Gameboost (page-based, `-updated_at` sort): how to handle sort instability
- Should backfill and incremental share a checkpoint or remain separate?

### Q4: Reprocess Command Design

Design the `reprocess_raw_payloads` management command:

- How does it know which provider's `parse_and_apply` to call?
- How does `failed → pending` reset work?
- Should it create a `SyncRun` for audit trail?
- Should it support `--dry-run`?

### Q5: `parse_and_apply` Abstraction

All 3 providers follow: extract fields → build defaults dict →
`Order.objects.update_or_create`. Is there a clean way to reduce this
repetition without over-abstracting? Or is the current pattern acceptable
given that field extraction logic differs significantly per provider?

### Q6: Error Handling Strategy

Propose a clear error handling taxonomy:

- Which errors should stop the entire sync run?
- Which errors should skip one item and continue?
- Which errors should be retried?
- How should each error type be recorded in `SyncRun.meta`?

---

## Expected Output Format

For each question, provide:

1. **Analysis**: What's wrong and why
2. **Proposed Solution**: Class/method-level design with signatures
3. **Provider Implementation**: How each provider (Eldorado, Gameboost, PA)
   implements the proposed hooks/interfaces
4. **Trade-offs**: What you considered and rejected, and why

At the end, provide a **Summary Implementation Roadmap** with:
- Ordered phases (what depends on what)
- Risk assessment per phase
- Which changes are breaking vs additive

---

## Constraints

- Python 3.12+, Django 5.x
- No new infrastructure (no Celery, no Redis, no message queues)
- Keep management commands as runtime interface
- Prefer composition over deep inheritance
- No type:ignore or noqa — type safety matters
- Tests should be possible with mocked providers (no real API calls)
- The solution must handle 2 additional providers (G2G, LZT) being added later
  without modifying base classes
