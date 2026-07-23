"""
Low-level PlayerAuctions API client.

Handles raw HTTP communication with the PlayerAuctions API.
Returns parsed response models with extracted metadata.
The facade layer handles auth header injection, proxy selection,
retry orchestration, and per-instance throttling.

PlayerAuctions response semantics are unusual:
- HTTP 200 does NOT guarantee success
- Must check ``isSuccess`` field (boolean) on 200 responses
- Must check ``StatusCode`` field (API-level status) on 200 responses
- Error messages are in ``message`` and ``code`` fields
- Retryable vs permanent errors are distinguished by message content

PlayerAuctions uses two base URLs:
- offer_base_url for offer/game endpoints
- order_base_url for order endpoints
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.marketplaces.playerauctions.config import PlayerAuctionsConfig
from apis_sdk.clients.marketplaces.playerauctions.endpoints import PlayerAuctionsEndpoints
from apis_sdk.clients.marketplaces.playerauctions.models import (
    PlayerAuctionsBulkUploadResponse,
    PlayerAuctionsCancelRequest,
    PlayerAuctionsCancelResponse,
    PlayerAuctionsCreateOfferResponse,
    PlayerAuctionsOffer,
    PlayerAuctionsOrderListItem,
    PlayerAuctionsOrderDetail,
    PlayerAuctionsPagination,
)


# -------------------------------------------------------------------------
# PlayerAuctions-specific error classification
# -------------------------------------------------------------------------

_RETRYABLE_PATTERNS: frozenset[str] = frozenset({
    # Note: "operated too frequent" is handled separately as RATE_LIMIT above
    "please try again later",
    "you have an offer creation in progress",
    "server error",
    "temporarily unavailable",
})

_PERMANENT_PATTERNS: frozenset[str] = frozenset({
    "suspected of fraud",
    "invalid input",
    "already exists",
    "forbidden",
    "invalid account",
    "account not found",
    "insufficient balance",
    "not real xlsx file",
    "please check!",
    "please input",
    "do not use web addresses",
})


def _classify_api_error(message: str) -> tuple[ErrorCategory, bool]:
    """Classify a PlayerAuctions API-level error message.

    Returns (error_category, is_retryable).
    """
    lower = message.lower()

    if "operated too frequent" in lower:
        return ErrorCategory.RATE_LIMIT, True

    if any(pat in lower for pat in _RETRYABLE_PATTERNS):
        return ErrorCategory.SERVER_ERROR, True

    if any(pat in lower for pat in _PERMANENT_PATTERNS):
        return ErrorCategory.VALIDATION, False

    # Unknown — be conservative, do not retry
    return ErrorCategory.UNKNOWN, False


class PlayerAuctionsClient:
    """
    Low-level PlayerAuctions API client.

    Handles:
    - Request execution via injected transport
    - Dual base URL routing (offer-api vs order-api)
    - PlayerAuctions response success/error normalization
    - Response parsing into PA-specific models
    - Error categorization from HTTP status and API-level fields

    Does NOT handle:
    - Authentication (injected via auth_headers parameter)
    - Retry logic (handled by facade/retry policy)
    - Proxy selection (handled by proxy pool)
    - Rate limiting / throttling (handled by facade)
    """

    PROVIDER = "playerauctions"

    def __init__(
        self,
        config: PlayerAuctionsConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()
        self._default_headers = config.get_default_headers()

    # ---------------------------------------------------------------------------
    # Offers — read operations
    # ---------------------------------------------------------------------------

    def list_offers(
        self,
        *,
        auth_headers: dict[str, str],
        page: int = 1,
        page_size: int = 50,
        listing_status: str = "",
        proxy_url: str | None = None,
    ) -> ApiResult[list[PlayerAuctionsOffer]]:
        """
        List seller offers with pagination.

        Returns parsed offers and pagination metadata in ``meta``.

        PA response structure::

            {
              "isSuccess": true,
              "data": {
                "count": 14,
                "items": [ {offerId, systemStatus, ...}, ... ]
              }
            }
        """
        params = {
            "pageIndex": str(page),
            "pageSize": str(page_size),
            "sortField": "null",
            "sortOrder": "null",
            "listingStatus": listing_status,
        }
        result = self._offer_request(
            HttpMethod.GET,
            PlayerAuctionsEndpoints.LIST_OFFERS,
            params=params,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        body = result.data
        # Offers are nested: {"data": {"items": [...], "count": N}}
        data_wrapper = body.get("data", {}) if isinstance(body, dict) else {}
        items_raw = data_wrapper.get("items", []) if isinstance(data_wrapper, dict) else []
        offers = [
            PlayerAuctionsOffer.model_validate(item)
            for item in items_raw
            if isinstance(item, dict)
        ]

        # Build pagination from count + page params
        meta = dict(result.meta)
        total_count = data_wrapper.get("count", 0) if isinstance(data_wrapper, dict) else 0
        if total_count:
            total_pages = (total_count + page_size - 1) // page_size
            meta["pagination"] = {
                "current_page": page,
                "total_pages": total_pages,
                "page_size": page_size,
                "total_count": total_count,
            }

        return ApiResult.success(
            offers,
            status_code=result.status_code,
            meta=meta,
        )

    def get_offer_details(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch a specific offer by ID.

        Returns the offer data dict (inner payload) on success.
        """
        path = PlayerAuctionsEndpoints.offer_details(offer_id)
        result = self._offer_request(
            HttpMethod.GET,
            path,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        # Extract inner data payload, consistent with list_offers
        body = result.data
        data = body.get("data", body) if isinstance(body, dict) else body

        return ApiResult.success(
            data,
            status_code=result.status_code,
            meta=dict(result.meta),
        )

    # ---------------------------------------------------------------------------
    # Orders — read operations
    # ---------------------------------------------------------------------------

    def list_seller_orders(
        self,
        *,
        auth_headers: dict[str, str],
        page: int = 1,
        page_size: int = 50,
        order_status: str = "All",
        product_type: str = "Accounts",
        proxy_url: str | None = None,
    ) -> ApiResult[list[PlayerAuctionsOrderListItem]]:
        """
        List seller orders with filters and pagination.

        Returns parsed order list items and total_count in ``meta``.
        The real response shape is: ``{"data": {"count": N, "items": [...]}}``.
        """
        params = {
            "pageIndex": str(page),
            "pageSize": str(page_size),
            "sortField": "null",
            "sortOrder": "null",
            "orderStatus": order_status,
            "productType": product_type,
            "orderId": "",
            "fromTime": "",
            "toTime": "",
        }
        result = self._mct_order_request(
            HttpMethod.GET,
            PlayerAuctionsEndpoints.LIST_SELLER_ORDERS,
            params=params,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        body = result.data
        # Orders are nested: {"data": {"items": [...], "count": N}}
        data_wrapper = body.get("data", {}) if isinstance(body, dict) else {}
        items_raw = data_wrapper.get("items", []) if isinstance(data_wrapper, dict) else []
        orders = [
            PlayerAuctionsOrderListItem.model_validate(item)
            for item in items_raw
            if isinstance(item, dict)
        ]

        meta = dict(result.meta)
        if isinstance(data_wrapper, dict):
            # Real API uses "count", accept both for safety
            count = data_wrapper.get("count") or data_wrapper.get("totalCount")
            if count is not None:
                meta["total_count"] = count

        return ApiResult.success(
            orders,
            status_code=result.status_code,
            meta=meta,
        )

    # ---------------------------------------------------------------------------
    # Orders — detail operations
    # ---------------------------------------------------------------------------

    def get_order_details(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsOrderDetail]:
        """
        Fetch order details by order ID.

        Returns a typed OrderDetail model with commonly used fields
        plus the full response data in ``extra``.
        """
        path = PlayerAuctionsEndpoints.order_details(order_id)
        result = self._mct_order_request(
            HttpMethod.GET,
            path,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        body = result.data
        data = body.get("data", body) if isinstance(body, dict) else body

        if isinstance(data, dict):
            # Known fields are parsed by the model; remaining go into extra
            _known_keys = set(PlayerAuctionsOrderDetail.model_fields.keys()) | {
                # Include alias names so they're not double-counted
                "tipsKey", "isDeliveryInfoVisible", "viewMessageUrl",
                "hasMessageLog", "stateImg", "orderInfo", "deliveryInfo",
                "orderCancellationInfo", "disbursementInfo", "refundInfo",
                "feedbackInfo", "eventLogs", "gameAccount",
                # Also the direct field names
                "id", "status", "title", "tips", "actions", "extensions",
            }
            extra = {k: v for k, v in data.items() if k not in _known_keys}
            # Merge extra into the data dict for model_validate
            parse_data = {**data, "extra": extra}
            detail = PlayerAuctionsOrderDetail.model_validate(parse_data)
        else:
            detail = PlayerAuctionsOrderDetail()

        return ApiResult.success(
            detail,
            status_code=result.status_code,
            meta=dict(result.meta),
        )

    # ---------------------------------------------------------------------------
    # Games — reference data
    # ---------------------------------------------------------------------------

    def game_account_servers(
        self,
        game_id: int,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        """
        Fetch server options for a game.

        Returns the server list from the response ``data`` field.
        The response shape is provider-native and returned as-is.
        """
        path = PlayerAuctionsEndpoints.game_account_servers(game_id)
        result = self._offer_request(
            HttpMethod.GET,
            path,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        body = result.data
        data = body.get("data", body) if isinstance(body, dict) else body
        servers = data if isinstance(data, list) else []

        return ApiResult.success(
            servers,
            status_code=result.status_code,
            meta=dict(result.meta),
        )

    # ---------------------------------------------------------------------------
    # Offers — write operations
    # ---------------------------------------------------------------------------

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsCreateOfferResponse]:
        """
        Create a single offer.

        The ``payload`` must be a provider-native dict built by the
        app-level payload builder. The SDK does NOT assemble game-specific
        or business-specific fields — it only transmits the request.

        Returns a minimal response model with the created offer ID.
        """
        result = self._offer_request(
            HttpMethod.POST,
            PlayerAuctionsEndpoints.CREATE_OFFER,
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        body = result.data
        # PA nests the created offer info: {"data": {"offerId": ...}}
        data = body.get("data", body) if isinstance(body, dict) else body
        if isinstance(data, dict):
            response_model = PlayerAuctionsCreateOfferResponse.model_validate(data)
        else:
            response_model = PlayerAuctionsCreateOfferResponse()

        return ApiResult.success(
            response_model,
            status_code=result.status_code,
            meta=dict(result.meta),
        )

    def cancel_offers(
        self,
        request: PlayerAuctionsCancelRequest,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsCancelResponse]:
        """
        Cancel offers by IDs.

        Accepts a ``PlayerAuctionsCancelRequest`` with offer IDs,
        filter parameters, and an ``is_all`` flag.
        """
        json_body = request.model_dump(by_alias=True)
        result = self._offer_request(
            HttpMethod.POST,
            PlayerAuctionsEndpoints.CANCEL_OFFERS,
            json_body=json_body,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        body = result.data
        if isinstance(body, dict):
            response_model = PlayerAuctionsCancelResponse(
                isSuccess=body.get("isSuccess", False),
                message=body.get("message", ""),
            )
        else:
            response_model = PlayerAuctionsCancelResponse()

        return ApiResult.success(
            response_model,
            status_code=result.status_code,
            meta=dict(result.meta),
        )

    # ---------------------------------------------------------------------------
    # Offers — bulk operations
    # ---------------------------------------------------------------------------

    def bulk_upload(
        self,
        file_path: str,
        *,
        product_type: str = "Accounts",
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsBulkUploadResponse]:
        """
        Upload an Excel file for bulk offer creation.

        The file must be a provider-ready ``.xlsx`` / ``.xls`` file
        built by the app-level payload builder.  The SDK only transmits
        the file — it does NOT generate or validate its content.

        PlayerAuctions expects a ``multipart/form-data`` request with:
        - ``file``: the Excel binary
        - ``productType``: typically ``"Accounts"``

        Returns a minimal response model containing the list of
        provider-native offer dicts created by the upload.
        """
        from pathlib import Path

        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        if ext in {".xlsx", ".xls"}:
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            mime = "text/csv"

        # Read into memory so the transport doesn't depend on an open
        # file handle (matches legacy V2 pattern).
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
        except OSError as exc:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                f"Cannot read upload file: {exc}",
                provider=self.PROVIDER,
            )

        files = {"file": (path_obj.name, file_bytes, mime)}
        form_data = {"productType": product_type}

        result = self._offer_request(
            HttpMethod.POST,
            PlayerAuctionsEndpoints.BULK_UPLOAD,
            data=form_data,
            files=files,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        # --- extract offers ---
        body = result.data
        offers: list[dict[str, Any]] = []
        if isinstance(body, dict):
            data_section = body.get("data", {})
            if isinstance(data_section, dict):
                offers = data_section.get("offers", [])
                if not offers:
                    # PA sometimes double-nests: data.data.offers
                    nested = data_section.get("data")
                    if isinstance(nested, dict):
                        offers = nested.get("offers", [])
            if not offers:
                offers = body.get("offers", [])

        response_model = PlayerAuctionsBulkUploadResponse(offers=offers)

        return ApiResult.success(
            response_model,
            status_code=result.status_code,
            meta={"offer_count": len(offers)},
        )

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _offer_request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Request against the offer base URL."""
        url = f"{self._config.offer_base_url}{path}"
        return self._request(method, url, json_body=json_body, params=params,
                             data=data, files=files,
                             auth_headers=auth_headers, proxy_url=proxy_url)

    def _order_request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Request against the order base URL using the generic PA contract."""
        url = f"{self._config.order_base_url}{path}"
        return self._request(method, url, json_body=json_body, params=params,
                             auth_headers=auth_headers, proxy_url=proxy_url)

    def _mct_order_request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Request seller orders with MCT's proven direct API contract.

        MCT successfully reads ``order-api.playerauctions.com`` with a fresh
        relay JWT, ``Accept``, and one browser user-agent.  The generic offer
        request envelope includes session cookies and browser-only headers
        which are useful for offer operations but cause the seller-order API
        to reject otherwise valid relay sessions.  Keep this narrow contract
        exclusively for read-only order endpoints.
        """
        url = f"{self._config.order_base_url}{path}"
        authorization = (
            auth_headers.get("Authorization")
            or auth_headers.get("authorization")
            or ""
        )
        user_agent = (
            auth_headers.get("User-Agent")
            or auth_headers.get("user-agent")
            or self._config.default_user_agent
        )
        direct_headers = {
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        if authorization:
            direct_headers["Authorization"] = authorization

        return self._request(
            method,
            url,
            json_body=json_body,
            params=params,
            auth_headers=direct_headers,
            proxy_url=proxy_url,
            base_headers={},
        )

    def _request(
        self,
        method: HttpMethod,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: Any | None = None,
        files: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
        base_headers: dict[str, str] | None = None,
    ) -> ApiResult[Any]:
        """Generic request with PlayerAuctions response normalization."""
        headers = {
            **(self._default_headers if base_headers is None else base_headers),
            **auth_headers,
        }
        try:
            response = self._transport.request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                params=params,
                data=data,
                files=files,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        # Non-200 HTTP status — standard error mapping
        if not response.is_success:
            return self._handle_http_error(response.status_code, response)

        # HTTP 200 — but PlayerAuctions may still report failure
        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse PlayerAuctions response: {exc}",
                provider=self.PROVIDER,
            )

        # Check isSuccess field (PA returns HTTP 200 with isSuccess=false)
        if isinstance(body, dict) and body.get("isSuccess", True) is False:
            message = body.get("message", "Unknown API error")
            code = body.get("code", 0)
            category, is_retryable = _classify_api_error(str(message))
            return ApiResult.from_error(
                category,
                str(message),
                status_code=200,
                provider=self.PROVIDER,
                is_retryable=is_retryable,
                details={"pa_code": code},
            )

        # Check StatusCode field (another PA error pattern)
        if isinstance(body, dict):
            api_status = body.get("StatusCode")
            if api_status is not None and api_status != 200:
                message = body.get("Message", f"API returned StatusCode: {api_status}")
                category, is_retryable = _classify_api_error(str(message))
                return ApiResult.from_error(
                    category,
                    str(message),
                    status_code=200,
                    provider=self.PROVIDER,
                    is_retryable=is_retryable,
                    details={"pa_status_code": api_status},
                )

        return ApiResult.success(body, status_code=response.status_code)

    def _handle_http_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            407: ErrorCategory.NETWORK,
            409: ErrorCategory.CONFLICT,
            422: ErrorCategory.VALIDATION,
            429: ErrorCategory.RATE_LIMIT,
        }

        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429 or status_code == 407

        retry_after: float | None = None
        if status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", 10))
            except (ValueError, TypeError, AttributeError):
                retry_after = 10.0

        # Try to extract message from response body
        message = f"HTTP {status_code}"
        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                message = str(body.get("message", body.get("Message", message)))
        except Exception:
            pass

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )
