"""
Low-level PlayerAuctions Official Seller API client.

Handles raw HTTP communication with the official PA Seller API.
Uses HMAC-SHA256 signing for every request (no bearer tokens).

Official API response semantics:
- code == 10000 → success
- code != 10000 → error (see PAErrorCode)
- requestId is included in every response for debugging

All endpoints use a single base URL: seller-api.playerauctions.com
"""

from __future__ import annotations

import json
from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

from .auth import PAOfficialAuth
from .config import PAOfficialConfig
from .endpoints import PAOfficialEndpoints
from .models import (
    PABulkUploadResponse,
    PACreateOfferResponse,
    PADeliveryTime,
    PAEnvelope,
    PAErrorCode,
    PAGame,
    PAImageUploadResponse,
    PAOfferDetail,
    PAOfferListItem,
    PAPrevalidation,
    PAServerNode,
    PACurrencyType,
)


# -------------------------------------------------------------------------
# Error classification
# -------------------------------------------------------------------------

def _classify_error_code(code: int) -> tuple[ErrorCategory, bool]:
    """Classify a PA official API error code.

    Returns (error_category, is_retryable).
    """
    prefix = code // 10000

    if prefix == 1:  # 1xxxx — parameter errors
        return ErrorCategory.VALIDATION, False
    if prefix == 2:  # 2xxxx — signature errors
        return ErrorCategory.AUTHENTICATION, False
    if prefix == 3:  # 3xxxx — auth/authorization errors
        return ErrorCategory.AUTHENTICATION, False
    if prefix == 4:  # 4xxxx — business errors
        return ErrorCategory.VALIDATION, False
    if prefix == 5:  # 5xxxx — server errors
        return ErrorCategory.SERVER_ERROR, True

    return ErrorCategory.UNKNOWN, False


class PAOfficialClient:
    """
    Low-level PlayerAuctions Official Seller API client.

    Handles:
    - HMAC-SHA256 signed requests
    - Official response envelope parsing (code == 10000)
    - Error classification from 5-digit error codes
    - All offer, game, media, and bulk endpoints

    Does NOT handle:
    - Retry logic (handled by facade)
    - Proxy selection (handled by facade)
    - Rate limiting / throttling (handled by facade)
    """

    PROVIDER = "playerauctions_official"

    def __init__(
        self,
        config: PAOfficialConfig,
        auth: PAOfficialAuth,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._auth = auth
        self._transport = transport
        self._logger = logger or NullLogger()

    # =====================================================================
    # Pre-validation
    # =====================================================================

    def creation_prevalidation(
        self,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[PAPrevalidation]:
        """Check seller eligibility before creating offers."""
        result = self._get(
            PAOfficialEndpoints.CREATION_PREVALIDATION,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        model = PAPrevalidation.model_validate(data) if isinstance(data, dict) else PAPrevalidation()
        return ApiResult.success(model, status_code=result.status_code, meta=dict(result.meta))

    # =====================================================================
    # Game metadata
    # =====================================================================

    def list_games(
        self,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[PAGame]]:
        """List all supported games."""
        result = self._get(
            PAOfficialEndpoints.GAMES,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        games = [
            PAGame.model_validate(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]
        return ApiResult.success(games, status_code=result.status_code, meta=dict(result.meta))

    def game_servers(
        self,
        game_id: int,
        product_type: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[PAServerNode]]:
        """Fetch server/faction tree for a game."""
        path = PAOfficialEndpoints.game_servers(game_id, product_type)
        result = self._get(path, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        nodes = [
            PAServerNode.model_validate(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]
        return ApiResult.success(nodes, status_code=result.status_code, meta=dict(result.meta))

    def game_currency_types(
        self,
        game_id: int,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[PACurrencyType]]:
        """Fetch currency types for multi-currency games."""
        path = PAOfficialEndpoints.game_currency_types(game_id)
        result = self._get(path, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        types = [
            PACurrencyType.model_validate(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]
        return ApiResult.success(types, status_code=result.status_code, meta=dict(result.meta))

    def game_item_categories(
        self,
        game_id: int,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        """Fetch item category tree for a game."""
        path = PAOfficialEndpoints.game_item_categories(game_id)
        return self._get_raw_data_list(path, proxy_url=proxy_url)

    def game_boosting_categories(
        self,
        game_id: int,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        """Fetch boosting categories for a game."""
        path = PAOfficialEndpoints.game_boosting_categories(game_id)
        return self._get_raw_data_list(path, proxy_url=proxy_url)

    def game_topup_categories(
        self,
        game_id: int,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        """Fetch top-up categories for a game."""
        path = PAOfficialEndpoints.game_topup_categories(game_id)
        return self._get_raw_data_list(path, proxy_url=proxy_url)

    def game_delivery_times(
        self,
        game_id: int,
        product_type: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[PADeliveryTime]]:
        """Fetch delivery time options for a game."""
        path = PAOfficialEndpoints.game_delivery_times(game_id, product_type)
        result = self._get(path, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        times = [
            PADeliveryTime.model_validate(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]
        return ApiResult.success(times, status_code=result.status_code, meta=dict(result.meta))

    # =====================================================================
    # Offer CRUD
    # =====================================================================

    def create_offer(
        self,
        product_type: str,
        payload: dict[str, Any],
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[PACreateOfferResponse]:
        """Create an offer for the given product type."""
        path = PAOfficialEndpoints.offer_by_type(product_type)
        result = self._post(path, json_body=payload, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        model = PACreateOfferResponse.model_validate(data) if isinstance(data, dict) else PACreateOfferResponse()
        return ApiResult.success(model, status_code=result.status_code, meta=dict(result.meta))

    def edit_offer(
        self,
        product_type: str,
        payload: dict[str, Any],
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[PACreateOfferResponse]:
        """Edit an offer (PUT). Payload must include offerId."""
        path = PAOfficialEndpoints.offer_by_type(product_type)
        result = self._put(path, json_body=payload, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        model = PACreateOfferResponse.model_validate(data) if isinstance(data, dict) else PACreateOfferResponse()
        return ApiResult.success(model, status_code=result.status_code, meta=dict(result.meta))

    def get_offer(
        self,
        product_type: str,
        offer_id: int,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[PAOfferDetail]:
        """Query a single offer by type and ID."""
        path = PAOfficialEndpoints.offer_detail(product_type, offer_id)
        result = self._get(path, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        if isinstance(data, dict):
            # Collect field aliases (camelCase) + Python names so we
            # correctly identify which keys are "extra" vs modelled.
            known_aliases: set[str] = set()
            for name, info in PAOfferDetail.model_fields.items():
                known_aliases.add(name)
                if info.alias:
                    known_aliases.add(info.alias)
            extra = {k: v for k, v in data.items() if k not in known_aliases}
            model = PAOfferDetail.model_validate({**data, "extra": extra})
        else:
            model = PAOfferDetail()
        return ApiResult.success(model, status_code=result.status_code, meta=dict(result.meta))

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
        proxy_url: str | None = None,
    ) -> ApiResult[list[PAOfferListItem]]:
        """List seller offers with pagination and filters."""
        params: dict[str, str] = {
            "pageIndex": str(page),
            "pageSize": str(page_size),
            "listingStatus": listing_status,
            "productType": product_type,
        }
        if keyword:
            params["keyword"] = keyword
        if game_id is not None:
            params["gameId"] = str(game_id)
        if server_id is not None:
            params["serverId"] = str(server_id)

        result = self._get(
            PAOfficialEndpoints.LIST_OFFERS,
            params=params,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        items_raw = data.get("items", []) if isinstance(data, dict) else []
        offers = [
            PAOfferListItem.model_validate(item)
            for item in items_raw
            if isinstance(item, dict)
        ]

        meta = dict(result.meta)
        if isinstance(data, dict):
            count = data.get("count", 0)
            if count:
                meta["pagination"] = {
                    "current_page": page,
                    "total_pages": (count + page_size - 1) // page_size,
                    "page_size": page_size,
                    "total_count": count,
                }

        return ApiResult.success(offers, status_code=result.status_code, meta=meta)

    def cancel_offers(
        self,
        *,
        offer_ids: list[int] | None = None,
        is_all: bool = False,
        parameters: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Cancel offers by IDs or filter."""
        body: dict[str, Any] = {"isAll": is_all}
        if offer_ids:
            body["offerIds"] = offer_ids
        if parameters:
            body["parameters"] = parameters
        return self._post(PAOfficialEndpoints.CANCEL_OFFERS, json_body=body, proxy_url=proxy_url)

    def set_display_status(
        self,
        *,
        flag: str,
        offer_ids: list[int] | None = None,
        is_all: bool = False,
        parameters: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Hide or show offers. flag = 'hide' or 'display'."""
        body: dict[str, Any] = {"flag": flag, "isAll": is_all}
        if offer_ids:
            body["offerIds"] = offer_ids
        if parameters:
            body["parameters"] = parameters
        return self._post(PAOfficialEndpoints.DISPLAY_STATUS, json_body=body, proxy_url=proxy_url)

    def cancellation_eligibility(
        self,
        *,
        offer_ids: list[int] | None = None,
        is_all: bool = False,
        parameters: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Check if offers can be cancelled."""
        body: dict[str, Any] = {"isAll": is_all}
        if offer_ids:
            body["offerIds"] = offer_ids
        if parameters:
            body["parameters"] = parameters
        return self._post(PAOfficialEndpoints.CANCELLATION_ELIGIBILITY, json_body=body, proxy_url=proxy_url)

    # =====================================================================
    # Bulk operations
    # =====================================================================

    def bulk_upload(
        self,
        file_path: str,
        *,
        product_type: str = "accounts",
        proxy_url: str | None = None,
    ) -> ApiResult[PABulkUploadResponse]:
        """Upload a filled bulk template (.xlsx) for offer creation."""
        from pathlib import Path

        path_obj = Path(file_path)
        try:
            file_bytes = path_obj.read_bytes()
        except OSError as exc:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                f"Cannot read upload file: {exc}",
                provider=self.PROVIDER,
            )

        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        files = {"file": (path_obj.name, file_bytes, mime)}
        form_fields = {"productType": product_type}

        result = self._multipart_post(
            PAOfficialEndpoints.BULK_UPLOAD,
            form_fields=form_fields,
            files=files,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        model = PABulkUploadResponse.model_validate(data) if isinstance(data, dict) else PABulkUploadResponse()
        return ApiResult.success(model, status_code=result.status_code, meta=dict(result.meta))

    # =====================================================================
    # Media / Images
    # =====================================================================

    def upload_image(
        self,
        file_path: str,
        game_id: int,
        *,
        image_type: str = "title",
        proxy_url: str | None = None,
    ) -> ApiResult[PAImageUploadResponse]:
        """Upload an image to the gallery."""
        from pathlib import Path

        path_obj = Path(file_path)
        try:
            file_bytes = path_obj.read_bytes()
        except OSError as exc:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                f"Cannot read image file: {exc}",
                provider=self.PROVIDER,
            )

        ext = path_obj.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_map.get(ext, "application/octet-stream")

        files = {"file": (path_obj.name, file_bytes, mime)}
        form_fields = {"type": image_type, "gameId": str(game_id)}

        result = self._multipart_post(
            PAOfficialEndpoints.MEDIA_IMAGES,
            form_fields=form_fields,
            files=files,
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        model = PAImageUploadResponse.model_validate(data) if isinstance(data, dict) else PAImageUploadResponse()
        return ApiResult.success(model, status_code=result.status_code, meta=dict(result.meta))

    def list_images(
        self,
        game_id: int,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[PAImageUploadResponse]]:
        """Query image gallery for a game."""
        result = self._get(
            PAOfficialEndpoints.MEDIA_IMAGES,
            params={"gameId": str(game_id)},
            proxy_url=proxy_url,
        )
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        images_raw = data.get("images", []) if isinstance(data, dict) else []
        images = [
            PAImageUploadResponse.model_validate(item)
            for item in images_raw
            if isinstance(item, dict)
        ]
        return ApiResult.success(images, status_code=result.status_code, meta=dict(result.meta))

    def delete_image(
        self,
        blob_name: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Delete an image from the gallery."""
        return self._delete(
            PAOfficialEndpoints.MEDIA_IMAGES,
            json_body={"blobName": blob_name},
            proxy_url=proxy_url,
        )

    # =====================================================================
    # Internal HTTP helpers
    # =====================================================================

    def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Signed GET request."""
        auth_headers = self._auth.build_signed_headers("")
        return self._request(HttpMethod.GET, path, params=params,
                             auth_headers=auth_headers, proxy_url=proxy_url)

    def _post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Signed POST request with JSON body."""
        body_str = json.dumps(json_body, separators=(",", ":"))
        auth_headers = self._auth.build_signed_headers(body_str)
        return self._request(HttpMethod.POST, path, json_body=json_body,
                             auth_headers=auth_headers, proxy_url=proxy_url)

    def _put(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Signed PUT request with JSON body."""
        body_str = json.dumps(json_body, separators=(",", ":"))
        auth_headers = self._auth.build_signed_headers(body_str)
        return self._request(HttpMethod.PUT, path, json_body=json_body,
                             auth_headers=auth_headers, proxy_url=proxy_url)

    def _delete(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Signed DELETE request."""
        body_str = json.dumps(json_body, separators=(",", ":")) if json_body else ""
        auth_headers = self._auth.build_signed_headers(body_str)
        return self._request(HttpMethod.DELETE, path, json_body=json_body,
                             auth_headers=auth_headers, proxy_url=proxy_url)

    def _multipart_post(
        self,
        path: str,
        *,
        form_fields: dict[str, str],
        files: dict[str, Any],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Signed multipart/form-data POST request."""
        auth_headers = self._auth.build_multipart_headers(form_fields)
        url = f"{self._config.base_url}{path}"
        headers = {**auth_headers, "accept": "application/json"}

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=headers,
                data=form_fields,
                files=files,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        return self._process_response(response)

    def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Execute an HTTP request against the official API."""
        url = f"{self._config.base_url}{path}"
        headers = {
            **auth_headers,
            "accept": "application/json",
            "content-type": "application/json",
        }

        try:
            response = self._transport.request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        return self._process_response(response)

    def _process_response(self, response: Any) -> ApiResult[Any]:
        """Normalize a response into ApiResult using the official envelope."""
        # Non-200 HTTP status
        if not response.is_success:
            return self._handle_http_error(response)

        # Parse JSON
        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse response: {exc}",
                provider=self.PROVIDER,
            )

        # Check official envelope: code == 10000 = success
        if isinstance(body, dict):
            code = body.get("code", 0)
            if code != PAErrorCode.SUCCESS:
                message = body.get("message", f"API error code: {code}")
                request_id = body.get("requestId", "")
                category, is_retryable = _classify_error_code(code)
                return ApiResult.from_error(
                    category,
                    str(message),
                    status_code=200,
                    provider=self.PROVIDER,
                    is_retryable=is_retryable,
                    details={"pa_code": code, "request_id": request_id},
                )

        return ApiResult.success(body, status_code=response.status_code)

    def _handle_http_error(self, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        status = response.status_code
        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            422: ErrorCategory.VALIDATION,
            429: ErrorCategory.RATE_LIMIT,
        }

        category = category_map.get(status, ErrorCategory.SERVER_ERROR)
        is_retryable = status >= 500 or status == 429

        retry_after: float | None = None
        if status == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", 10))
            except (ValueError, TypeError, AttributeError):
                retry_after = 10.0

        message = f"HTTP {status}"
        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                message = str(body.get("message", body.get("Message", message)))
        except Exception:
            pass

        return ApiResult.from_error(
            category,
            message,
            status_code=status,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )

    # =====================================================================
    # Data extraction helpers
    # =====================================================================

    @staticmethod
    def _extract_data(body: Any) -> Any:
        """Extract the data field from the response envelope."""
        if isinstance(body, dict):
            return body.get("data", body)
        return body

    def _get_raw_data_list(
        self,
        path: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        """GET endpoint that returns a list of raw dicts."""
        result = self._get(path, proxy_url=proxy_url)
        if not result.ok:
            return result  # type: ignore[return-value]

        data = self._extract_data(result.data)
        items = data if isinstance(data, list) else []
        return ApiResult.success(items, status_code=result.status_code, meta=dict(result.meta))
