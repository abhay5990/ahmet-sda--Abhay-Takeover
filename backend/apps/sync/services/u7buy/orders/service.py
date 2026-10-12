"""U7Buy seller-order sync with manual-delivery safety.

No credential material is read from or written to U7Buy orders.  The normal
SDA order pipeline links a verified offer ID to its Listing and consumes pool
stock only after U7Buy reaches a confirmed sale state.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.sync.enums import ResourceType, SyncMode, SyncRunStatus
from apps.sync.models import RawPayload, SyncCheckpoint, SyncRun
from apps.sync.services.base import BaseSyncService
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


class U7BuyOrderSyncService(BaseSyncService):
    resource_type = ResourceType.ORDERS
    DEFAULT_PAGE_SIZE = 100

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        page = int(checkpoint.meta.get("_incremental_page", 1)) if checkpoint.mode == SyncMode.INCREMENTAL else int(checkpoint.cursor or 1)
        result = self.provider.fetch_orders(
            self.client,
            pageNum=page,
            pageSize=self.DEFAULT_PAGE_SIZE,
        )
        if not result.ok:
            message = result.error.message if result.error else "unknown error"
            raise RuntimeError(f"U7Buy order list failed: {message}")

        data = result.data or {}
        rows = data.get("rows") or data.get("pageResult") or data.get("items") or []
        items = [dict(row) for row in rows if isinstance(row, dict)]
        total = int(data.get("total") or data.get("totalCount") or len(items) or 0)
        next_cursor = str(page + 1) if page * self.DEFAULT_PAGE_SIZE < total else ""
        if checkpoint.mode == SyncMode.INCREMENTAL and next_cursor:
            checkpoint.meta = {**checkpoint.meta, "_incremental_page": page + 1}
            checkpoint.save(update_fields=["meta", "updated_at"])
        elif checkpoint.mode == SyncMode.INCREMENTAL and "_incremental_page" in checkpoint.meta:
            checkpoint.meta = {k: v for k, v in checkpoint.meta.items() if k != "_incremental_page"}
            checkpoint.save(update_fields=["meta", "updated_at"])
        return items, next_cursor

    def is_already_seen(self, item: dict, stop_remote_id: str) -> bool:
        return bool(stop_remote_id and mapper.extract_remote_id(item) == stop_remote_id)

    def extract_remote_id(self, item: dict) -> str:
        return mapper.extract_remote_id(item)

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_timestamp(item.get("orderTimestamp") or item.get("placedTime"))

    def prepare_item(self, item: dict, account: IntegrationAccount) -> tuple[dict, dict]:
        remote_id = mapper.extract_remote_id(item)
        if not remote_id:
            raise ValueError("U7Buy order has no order ID")
        # A detail read is authoritative for the exact state but summary data is
        # still safely persisted if the optional detail endpoint is temporarily
        # unavailable. The next poll can enrich and reapply it.
        try:
            detail = self.client.get_order(remote_id)
        except Exception as exc:
            logger.warning("U7Buy order detail unavailable for %s: %s", remote_id, exc.__class__.__name__)
            return item, {"detail": "unavailable"}
        return {**item, **detail}, {"detail": "read"}

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        payload = raw_payload.payload
        price, currency = mapper.parse_price(payload)
        defaults: dict[str, Any] = {
            # User-directed manual delivery is the only supported U7Buy mode.
            "is_instant": False,
            "product_category": mapper.map_category(payload),
            "status": mapper.map_status(payload),
            "price": Decimal(str(price)),
            "currency": currency,
            "our_fee": None,
            "sold_at": mapper.parse_timestamp(payload.get("orderTimestamp") or payload.get("placedTime")),
            "store_listing_id": mapper.extract_listing_id(payload),
            "raw_data": payload,
        }
        from apps.inventory.services import resolve_game
        game_external_id = mapper.extract_game_external_id(payload)
        if game_external_id:
            game = resolve_game("u7buy", game_external_id)
            if game:
                defaults["game"] = game
        return self._upsert_order(raw_payload, defaults)

    def recover_order_by_id(self, account: IntegrationAccount, order_id: str) -> str:
        """Read and apply a single signed-webhook order without moving cursors."""
        remote_id = str(order_id).strip()
        if not remote_id:
            raise ValueError("U7Buy order ID is required")
        detail = self.client.get_order(remote_id)
        if not isinstance(detail, dict):
            raise RuntimeError("U7Buy order detail response is invalid")
        detail.setdefault("orderId", remote_id)
        run = SyncRun.objects.create(
            integration_account=account,
            resource_type=self.resource_type,
            mode=SyncMode.INCREMENTAL,
        )
        try:
            prepared, meta = self.prepare_item(detail, account)
            raw = self._ingest_raw(account, remote_id, prepared)
            if meta:
                raw.meta = {**raw.meta, **meta, "source": "u7buy_webhook"}
                raw.save(update_fields=["meta", "updated_at"])
            applied = self._try_parse(raw, run)
            run.processed_count = 1
            run.save(update_fields=["processed_count", "created_count", "updated_count", "error_count", "updated_at"])
            if not applied:
                run.finish(SyncRunStatus.FAILED)
                return "parse_failed"
            run.finish(SyncRunStatus.COMPLETED)
            return "recovered"
        except Exception:
            run.finish(SyncRunStatus.FAILED)
            raise
