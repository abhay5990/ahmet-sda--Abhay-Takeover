"""
RBXCrate high-level facade.

Provides a clean consumer-facing API that coordinates:
- Authentication (static API key, externally managed)
- Error boundary (client exceptions → ApiResult)

This facade is intentionally thin.  RBXCrate is a simple service
with no proxy, throttle, or retry requirements at the SDK level.
Retry and orchestration may be added later if needed.

Deferred responsibilities (remain outside the SDK):
- DB/config-based API key reload
- Order workflow orchestration
- Game-specific payload assembly
"""

from __future__ import annotations

from typing import Any, Protocol

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.auth.base import BaseAuthProvider


class RbxCrateApiClient(Protocol):
    """Protocol for the low-level RBXCrate client."""

    def get_stock(
        self, *, auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def get_detailed_stock(
        self, *, auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def get_order_info(
        self, order_id: str, *, auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def cancel_order(
        self, order_id: str, *, auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def create_gamepass_order(
        self,
        *,
        order_id: str,
        roblox_username: str,
        robux_amount: int,
        place_id: int,
        is_pre_order: bool = True,
        check_ownership: bool = False,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def resend_gamepass_order(
        self,
        *,
        order_id: str,
        place_id: int,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...


class RbxCrateFacade:
    """
    High-level RBXCrate interface.

    Coordinates authentication around the low-level RbxCrateClient.
    All methods return ApiResult — no exceptions escape.
    """

    def __init__(
        self,
        client: RbxCrateApiClient,
        auth: BaseAuthProvider,
    ) -> None:
        self._client = client
        self._auth = auth

    def _headers(self) -> dict[str, str]:
        return self._auth.get_auth_headers()

    # ---------------------------------------------------------------------------
    # Stock (reads)
    # ---------------------------------------------------------------------------

    def get_stock(self) -> ApiResult[dict[str, Any]]:
        """Fetch current Robux stock."""
        try:
            return self._client.get_stock(auth_headers=self._headers())
        except Exception as exc:
            return self._error(exc)

    def get_detailed_stock(self) -> ApiResult[dict[str, Any]]:
        """Fetch detailed Robux stock information."""
        try:
            return self._client.get_detailed_stock(auth_headers=self._headers())
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Order info (read-like)
    # ---------------------------------------------------------------------------

    def get_order_info(self, order_id: str) -> ApiResult[dict[str, Any]]:
        """Query order status and details."""
        try:
            return self._client.get_order_info(
                order_id, auth_headers=self._headers(),
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Order management (writes — non-idempotent)
    # ---------------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> ApiResult[dict[str, Any]]:
        """Cancel an order (only Error/Queued status)."""
        try:
            return self._client.cancel_order(
                order_id, auth_headers=self._headers(),
            )
        except Exception as exc:
            return self._error(exc)

    def create_gamepass_order(
        self,
        *,
        order_id: str,
        roblox_username: str,
        robux_amount: int,
        place_id: int,
        is_pre_order: bool = True,
        check_ownership: bool = False,
    ) -> ApiResult[dict[str, Any]]:
        """Create a new gamepass order."""
        try:
            return self._client.create_gamepass_order(
                order_id=order_id,
                roblox_username=roblox_username,
                robux_amount=robux_amount,
                place_id=place_id,
                is_pre_order=is_pre_order,
                check_ownership=check_ownership,
                auth_headers=self._headers(),
            )
        except Exception as exc:
            return self._error(exc)

    def resend_gamepass_order(
        self,
        *,
        order_id: str,
        place_id: int,
    ) -> ApiResult[dict[str, Any]]:
        """Retry a failed gamepass order."""
        try:
            return self._client.resend_gamepass_order(
                order_id=order_id,
                place_id=place_id,
                auth_headers=self._headers(),
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    @staticmethod
    def _error(exc: Exception) -> ApiResult[Any]:
        return ApiResult.from_error(
            ErrorCategory.UNKNOWN,
            f"Unexpected RBXCrate facade error: {exc}",
            provider="rbxcrate",
            is_retryable=False,
        )
