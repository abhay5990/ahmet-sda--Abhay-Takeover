"""
PlayerAuctions Official Seller API high-level facade.

Provides a clean consumer-facing API that coordinates:
- HMAC-SHA256 authentication (per-request signing)
- Optional proxy selection
- Retry policy execution with strategy-driven actions
- Per-instance request throttling

Unlike the legacy PA facade, this one signs each request individually
(no bearer token, no token refresh).
"""

from __future__ import annotations

import time
from typing import Any

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy
from apis_sdk.clients.marketplaces._facade_support import FacadeExecutor

from .auth import PAOfficialAuth
from .client import PAOfficialClient
from .models import (
    PABulkUploadResponse,
    PACreateOfferResponse,
    PACurrencyType,
    PADeliveryTime,
    PAGame,
    PAImageUploadResponse,
    PAOfferDetail,
    PAOfferListItem,
    PAPrevalidation,
    PAServerNode,
)


class PAOfficialFacade:
    """
    High-level PlayerAuctions Official Seller API interface.

    Coordinates HMAC signing, proxy rotation, retry logic,
    and per-instance throttling around the low-level client.

    Read/idempotent operations use execute_with_retry().
    Write operations use execute_once() to prevent duplicate side effects.
    """

    def __init__(
        self,
        client: PAOfficialClient,
        auth: PAOfficialAuth,
        *,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        rate_limit_delay: float = 1.0,
        logger=None,
    ) -> None:
        self._client = client
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: float | None = None
        self._exec = FacadeExecutor(
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=retry_policy,
            retry_strategy=retry_strategy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
            provider_name="playerauctions_official",
            pre_execute=self._throttle,
        )

    def _throttle(self) -> None:
        """Enforce per-instance minimum delay between requests."""
        if self._rate_limit_delay <= 0:
            return
        now = time.monotonic()
        if self._last_request_time is not None:
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.monotonic()

    # =====================================================================
    # Pre-validation
    # =====================================================================

    def creation_prevalidation(
        self,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PAPrevalidation]:
        """Check seller eligibility before creating offers."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.creation_prevalidation(proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    # =====================================================================
    # Game metadata (all idempotent reads)
    # =====================================================================

    def list_games(
        self,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[PAGame]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_games(proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def game_servers(
        self,
        game_id: int,
        product_type: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[PAServerNode]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_servers(game_id, product_type, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def game_currency_types(
        self,
        game_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[PACurrencyType]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_currency_types(game_id, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def game_item_categories(
        self,
        game_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_item_categories(game_id, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def game_boosting_categories(
        self,
        game_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_boosting_categories(game_id, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def game_topup_categories(
        self,
        game_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_topup_categories(game_id, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def game_delivery_times(
        self,
        game_id: int,
        product_type: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[PADeliveryTime]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_delivery_times(game_id, product_type, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    # =====================================================================
    # Offer CRUD
    # =====================================================================

    def create_offer(
        self,
        product_type: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PACreateOfferResponse]:
        """Create an offer (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_offer(product_type, payload, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def edit_offer(
        self,
        product_type: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PACreateOfferResponse]:
        """Edit an offer (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.edit_offer(product_type, payload, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def get_offer(
        self,
        product_type: str,
        offer_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PAOfferDetail]:
        """Query a single offer (idempotent read)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_offer(product_type, offer_id, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    # =====================================================================
    # Offer management
    # =====================================================================

    def list_offers(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        listing_status: str = "active",
        product_type: str = "all",
        keyword: str = "",
        game_id: int | None = None,
        server_id: int | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[PAOfferListItem]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_offers(
                page=page, page_size=page_size, listing_status=listing_status,
                product_type=product_type, keyword=keyword,
                game_id=game_id, server_id=server_id, proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def cancel_offers(
        self,
        *,
        offer_ids: list[int] | None = None,
        is_all: bool = False,
        parameters: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Cancel offers (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.cancel_offers(
                offer_ids=offer_ids, is_all=is_all,
                parameters=parameters, proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def set_display_status(
        self,
        *,
        flag: str,
        offer_ids: list[int] | None = None,
        is_all: bool = False,
        parameters: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Hide or show offers (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.set_display_status(
                flag=flag, offer_ids=offer_ids, is_all=is_all,
                parameters=parameters, proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def cancellation_eligibility(
        self,
        *,
        offer_ids: list[int] | None = None,
        is_all: bool = False,
        parameters: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.cancellation_eligibility(
                offer_ids=offer_ids, is_all=is_all,
                parameters=parameters, proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # =====================================================================
    # Bulk operations
    # =====================================================================

    def bulk_upload(
        self,
        file_path: str,
        *,
        product_type: str = "accounts",
        proxy_group: str | None = None,
    ) -> ApiResult[PABulkUploadResponse]:
        """Upload bulk template (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.bulk_upload(
                file_path, product_type=product_type, proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # =====================================================================
    # Media / Images
    # =====================================================================

    def upload_image(
        self,
        file_path: str,
        game_id: int,
        *,
        image_type: str = "title",
        proxy_group: str | None = None,
    ) -> ApiResult[PAImageUploadResponse]:
        """Upload an image (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.upload_image(
                file_path, game_id, image_type=image_type, proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_images(
        self,
        game_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[PAImageUploadResponse]]:
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_images(game_id, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )

    def delete_image(
        self,
        blob_name: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Delete an image (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.delete_image(blob_name, proxy_url=proxy_url),
            proxy_group=proxy_group,
        )
