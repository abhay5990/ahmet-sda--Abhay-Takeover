"""U7Buy account-offer provider.

This client intentionally supports no automatic delivery.  It is a narrow seller
integration for catalog reads, manual-delivery account offers, offer lifecycle,
and order-detail reads used by the normal SDA synchronization pipeline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential


DEFAULT_BASE_URL = "https://openapi.u7buy.com/prod-api"
WEBHOOK_SIGNATURE_HEADER = "HTTP_X_U7BUY_SIGNATURE"


class U7BuyApiError(RuntimeError):
    """Raised for a U7Buy transport or API failure without leaking secrets."""


@dataclass(frozen=True)
class U7BuyClient:
    app_id: str
    app_secret: str
    base_url: str = DEFAULT_BASE_URL
    session: requests.Session | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.session or requests.Session()
        try:
            response = session.request(
                method,
                f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                params=params,
                json=payload,
                auth=(self.app_id, self.app_secret),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise U7BuyApiError(f"U7Buy request failed: {exc.__class__.__name__}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise U7BuyApiError(f"U7Buy returned non-JSON HTTP {response.status_code}") from exc
        if response.status_code >= 400 or int(body.get("code", 0) or 0) != 200:
            message = str(body.get("msg") or f"HTTP {response.status_code}")
            raise U7BuyApiError(f"U7Buy API rejected request: {message[:240]}")
        data = body.get("data")
        return data if isinstance(data, dict) else {"items": data or []}

    def list_game_services(self) -> dict[str, Any]:
        return self._request("GET", "/open-api/game_service_offer/v2/get_spu_list")

    def get_game_service_spu(self, spu_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/open-api/game_service_offer/v2/get_spu_detail",
            params={"spuId": spu_id},
        )

    def list_offers(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/open-api/offer_common/list", params=params)

    def get_offer(self, offer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/open-api/game_service_offer/v2/{offer_id}")

    def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._request("POST", "/open-api/game_service_offer/v2", payload=payload)
        except U7BuyApiError as exc:
            if "already exists" not in str(exc).lower():
                raise
            response = {}
        direct_id = _extract_offer_id(response)
        if direct_id:
            return {"offerId": direct_id}
        recovered = self._recover_exact_offer_id(str(payload.get("offerName") or ""))
        if not recovered:
            raise U7BuyApiError("U7Buy create outcome could not be verified by exact offer name")
        return {"offerId": recovered}

    def _recover_exact_offer_id(self, offer_name: str) -> str:
        """Return an ID only when the remote exact-name match is unique."""
        if not offer_name:
            return ""
        matches: list[str] = []
        page = 1
        while page <= 20:
            data = self.list_offers(
                pageNum=page,
                pageSize=100,
                businessId="1820693954263351302",
            )
            rows = data.get("rows") or data.get("pageResult") or data.get("items") or []
            for row in rows:
                if isinstance(row, dict) and str(row.get("productName") or row.get("offerName") or "") == offer_name:
                    candidate = _extract_offer_id(row)
                    if candidate:
                        matches.append(candidate)
            total = int(data.get("total") or data.get("totalCount") or len(rows) or 0)
            if page * 100 >= total:
                break
            page += 1
        return matches[0] if len(set(matches)) == 1 else ""

    def update_offer(self, offer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/open-api/game_service_offer/v2",
            payload={"offerId": offer_id, **payload},
        )

    def off_sale_offer(self, offer_id: str) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/open-api/offer_common/status",
            payload=[{"offerId": offer_id, "status": 0, "businessType": "Game Service"}],
        )

    def delete_offer(self, offer_id: str) -> dict[str, Any]:
        """Apply U7Buy's required off-sale then delete lifecycle once."""
        try:
            self.off_sale_offer(offer_id)
        except U7BuyApiError:
            # An already-off-sale offer may reject the status update. Deletion
            # is still the authoritative next operation and remains idempotent.
            pass
        return self._request(
            "DELETE",
            "/open-api/offer_common",
            payload=[{"offerId": offer_id, "businessType": "Game Service"}],
        )

    def list_orders(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/open-api/order/list", params=params)

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/open-api/order/{order_id}")


def webhook_signature_is_valid(*, raw_body: bytes, supplied_signature: str, app_id: str, app_secret: str) -> bool:
    """Validate U7Buy's documented HMAC of ``App ID + ',' + raw JSON``."""
    if not raw_body or not supplied_signature or not app_id or not app_secret:
        return False
    message = app_id.encode("utf-8") + b"," + raw_body
    expected = hmac.new(app_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied_signature.strip().lower())


def _extract_offer_id(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("offerId", "offer_id", "id", "listingId", "listing_id"):
        candidate = value.get(key)
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    nested = value.get("data")
    return _extract_offer_id(nested) if isinstance(nested, dict) else ""


@register_provider
class U7BuyProvider(AbstractProvider):
    provider_name = "u7buy"
    display_name = "U7Buy"

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        return [
            CredentialField("app_id", "U7Buy App ID", field_type="text"),
            CredentialField("app_secret", "U7Buy App Secret", field_type="password"),
            CredentialField(
                "game_service_config",
                "Verified game-service catalog JSON",
                field_type="textarea",
                required=False,
                help_text=(
                    "Optional until a game is enabled. Map the SDA game slug to its verified "
                    "U7Buy entity_id, spu_id, and any required delivery/attribute IDs."
                ),
            ),
            CredentialField(
                "webhook_secret",
                "Webhook signing secret (optional override)",
                field_type="password",
                required=False,
                help_text="Uses the encrypted App Secret when blank. Never add callback URLs or secrets to source code.",
            ),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> U7BuyClient:
        creds = credential.credentials or {}
        return U7BuyClient(
            app_id=str(creds.get("app_id") or ""),
            app_secret=str(creds.get("app_secret") or ""),
            base_url=str(creds.get("base_url") or DEFAULT_BASE_URL),
        )

    @staticmethod
    def _result(fn) -> ApiResult:
        try:
            return ApiResult.success(fn())
        except U7BuyApiError as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                str(exc),
                provider="u7buy",
            )

    def fetch_products(self, client: U7BuyClient, **kwargs: Any) -> ApiResult:
        return self._result(lambda: client.list_game_services())

    def create_listing(self, client: U7BuyClient, product_data: dict) -> ApiResult:
        return self._result(lambda: client.create_offer(product_data.get("payload", product_data)))

    def update_listing(self, client: U7BuyClient, external_id: str, product_data: dict) -> ApiResult:
        return self._result(lambda: client.update_offer(external_id, product_data.get("payload", product_data)))

    def delete_listing(self, client: U7BuyClient, external_id: str, **kwargs: Any) -> ApiResult:
        return self._result(lambda: client.delete_offer(external_id))

    def fetch_orders(self, client: U7BuyClient, **kwargs: Any) -> ApiResult:
        return self._result(lambda: client.list_orders(**kwargs))
