from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.sync.enums import ResourceType, SyncMode
from apps.sync.exceptions import SkipItem
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from apps.posting.services.stock.pa_tracking import extract_tracking_code
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


def _payload_text_values(value: Any):
    """Yield scalar text from a PA order payload, including nested detail data."""
    if isinstance(value, dict):
        for nested in value.values():
            yield from _payload_text_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _payload_text_values(nested)
    elif isinstance(value, (str, int, float)):
        yield str(value)


class PlayerAuctionsOrderSyncService(BaseSyncService):
    """Order sync orchestration for PlayerAuctions.

    Hooks used:
        - ``should_skip_item``: skip statuses that indicate incomplete
          orders (Pending Payment, Buyer Cancelled, etc.)
        - ``prepare_item``: per-order detail fetch + merge. Raises
          ``SkipItem`` on detail failure (BD-1: no partial raw).
        - ``is_already_seen``: incremental stop condition.

    Direction:
        - API only supports newest-first pagination. Both backfill and
          incremental iterate newest → oldest.
    """

    resource_type = ResourceType.ORDERS

    DEFAULT_ORDER_STATUS = 'All'
    DEFAULT_PRODUCT_TYPE = 'Accounts'
    DEFAULT_PAGE_SIZE = 50

    SKIP_STATUSES: frozenset[str] = frozenset({
        'Pending Payment',
        'Offer Unavailable',
        'Buyer Cancelled',
        'Order Unavailable',
        'Payment Failed',
    })

    def __init__(
        self,
        provider=None,
        client=None,
        *,
        order_status: str | None = None,
        product_type: str | None = None,
    ) -> None:
        self.provider = provider
        self.client = client
        self.order_status = order_status or self.DEFAULT_ORDER_STATUS
        self.product_type = product_type or self.DEFAULT_PRODUCT_TYPE

    def run(self, account, mode, phase='full'):
        """Reset auth failure flag before each sync run."""
        if self.client and hasattr(self.client, 'reset_auth_failure'):
            self.client.reset_auth_failure()
        return super().run(account, mode, phase)

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of order summaries from PlayerAuctions.

        Always newest-first (API constraint). Backfill resumes from
        checkpoint cursor; incremental tracks page in meta.
        """
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

        items: list[dict] = []
        for order in result.data or []:
            if hasattr(order, 'model_dump'):
                items.append(order.model_dump())
            elif isinstance(order, dict):
                items.append(order)
            else:
                items.append(dict(order))

        if not items:
            return [], ''

        # Determine next page from total_count metadata
        total_count = result.meta.get('total_count', 0)
        if isinstance(total_count, str):
            total_count = int(total_count)

        total_pages = (
            (total_count + self.DEFAULT_PAGE_SIZE - 1)
            // self.DEFAULT_PAGE_SIZE
            if total_count else 0
        )

        next_cursor = str(page + 1) if page < total_pages else ''

        # Track page progression for incremental mode
        if checkpoint.mode == SyncMode.INCREMENTAL and next_cursor:
            checkpoint.meta = {
                **checkpoint.meta,
                '_incremental_page': page + 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

        return items, next_cursor

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Stop incremental sync when we hit an already-seen order."""
        if not stop_remote_id:
            return False
        return self.extract_remote_id(item) == stop_remote_id

    def should_skip_item(self, item: dict) -> bool:
        """Skip orders with statuses that indicate never-completed orders."""
        return (item.get('status') or '') in self.SKIP_STATUSES

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Prepare a seller-order summary for persistence.

        MCT's production-proven PlayerAuctions flow uses the seller-order list
        response directly.  That response already contains the order ID,
        offer ID, status, price, and timestamp needed to record a sale and
        match it to a pool clone.  The optional order-detail endpoint is
        inconsistent for historical orders and must not prevent a verified
        summary from being stored.
        """
        return item, {}

    def extract_remote_id(self, item: dict) -> str:
        return str(
            item.get('order_id')
            or item.get('orderId')
            or item.get('id')
            or '',
        ).strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_pa_datetime(
            item.get('create_time') or item.get('createTime') or '',
        )

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw PlayerAuctions order payload and upsert into Order."""
        payload = raw_payload.payload

        # Status: prefer detail nested object, fall back to list string
        status_str = mapper.extract_status_from_detail(payload)
        if not status_str:
            status_str = payload.get('status') or ''

        # Price
        order_info = (
            payload.get('order_info') or payload.get('orderInfo') or {}
        )
        price_str = order_info.get('price') or payload.get('price') or ''
        price_value, currency = mapper.parse_price_string(price_str)

        # Sold at
        create_time = (
            payload.get('create_time') or payload.get('createTime') or ''
        )
        sold_at = mapper.parse_pa_datetime(create_time)

        # Product category
        product_type = (
            payload.get('product_type') or payload.get('productType') or ''
        )
        product_category = mapper.map_category(product_type)

        # Listing reference.  PlayerAuctions exposes offerId on the
        # SellerOrders summary (the same source MCT uses).  Prefer it so pool
        # sale attribution does not depend on the less reliable detail route.
        listing_id = str(
            payload.get('offer_id')
            or payload.get('offerId')
            or mapper.extract_listing_id_from_detail(payload)
            or ''
        )

        # Native offer IDs are authoritative.  A per-listing PA title code is
        # a deliberately narrow fallback for API payloads that omit offerId.
        # It maps the order to the exact locally persisted Listing, which in
        # turn restores the canonical offer ID before pool-sale handling runs.
        linked_listing = None
        if not listing_id and raw_payload.integration_account_id:
            tracking_code = extract_tracking_code(*_payload_text_values(payload))
            if tracking_code:
                from apps.listings.models import Listing
                linked_listing = (
                    Listing.objects.filter(
                        integration_account=raw_payload.integration_account,
                        title__icontains=f'[{tracking_code}]',
                    )
                    .order_by('-listed_at', '-id')
                    .first()
                )
                if linked_listing:
                    listing_id = linked_listing.store_listing_id
                    logger.info(
                        'PlayerAuctions order %s matched Listing #%s by tracking code %s',
                        self.extract_remote_id(payload), linked_listing.id, tracking_code,
                    )

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

        if linked_listing:
            # Prevent BaseSyncService from discarding the verified title-code
            # link when it applies its normal store_listing_id lookup.
            defaults['listing'] = linked_listing
            if linked_listing.dropship_product_id:
                defaults['dropship_product'] = linked_listing.dropship_product

        # Game resolve
        from apps.inventory.services import resolve_game
        game_ext_id = mapper.extract_game_external_id(payload)
        if game_ext_id:
            game = resolve_game('playerauctions', game_ext_id)
            if game:
                defaults['game'] = game

        # OwnedProduct get-or-create
        owned = self._match_or_create_owned_product(
            payload, raw_payload, Decimal(str(price_value)), currency,
        )
        if owned:
            defaults['owned_product'] = owned

        return self._upsert_order(raw_payload, defaults)

    def _match_or_create_owned_product(self, payload: dict, raw_payload: RawPayload,
                                       price: Decimal, currency: str):
        """Match or create OwnedProduct from order credentials.

        PA orders only have loginName — password defaults to 'nopassworddetected'.
        """
        from apps.inventory.enums import OwnedProductStatus
        from apps.inventory.services import resolve_game
        from apps.sync.services.shared.owned_product import get_or_create_owned_product

        parsed = mapper.to_parsed_credentials(payload)
        if not parsed.login:
            return None

        game_slug = mapper.extract_game_external_id(payload)
        if not game_slug:
            return None

        game = resolve_game('playerauctions', game_slug)
        if not game or not game.category:
            return None

        cost = price / 2 if price else None

        return get_or_create_owned_product(
            parsed=parsed,
            category=game.category,
            game=game,
            source_account=raw_payload.integration_account,
            status=OwnedProductStatus.SOLD,
            price=cost,
            currency=currency,
            raw_data=payload,
        )

    # ── Private helpers ───────────────────────────────────────────────

    def _fetch_and_merge_detail(
        self,
        summary: dict,
        remote_id: str,
    ) -> dict | None:
        """Fetch order detail and merge with list summary.

        Returns the merged dict, or ``None`` if detail fetch fails.
        """
        try:
            result = self.provider.fetch_order_details(
                self.client, remote_id,
            )
            if not result.ok:
                logger.warning(
                    "PA detail fetch failed for order %s: %s",
                    remote_id,
                    result.error.message if result.error else 'unknown error',
                )
                return None

            detail_data = result.data
            if hasattr(detail_data, 'model_dump'):
                detail_dict = detail_data.model_dump()
            elif isinstance(detail_data, dict):
                detail_dict = detail_data
            else:
                detail_dict = dict(detail_data)

            # Merge: summary as base, detail overlaid
            merged = {**summary, **detail_dict}

            # Ensure list-level fields survive the merge
            for key in (
                'create_time', 'createTime',
                'product_type', 'productType',
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

