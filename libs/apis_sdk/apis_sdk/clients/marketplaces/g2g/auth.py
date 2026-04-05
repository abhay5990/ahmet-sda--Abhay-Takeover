"""
G2G authentication provider.

Implements a reactive-only token refresh model:
- Tokens are set with effectively infinite expiry
- Refresh only happens via the retry path (401/403 -> strategy -> runtime)
- Refresh calls POST /user/refresh_access with multi-token payload
- Uses an injected shared transport for the refresh HTTP call

This is distinct from Eldorado (Cognito SRP) and GameBoost (static bearer).
"""

from __future__ import annotations

import time

from apis_sdk.core.enums import HttpMethod
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger


class G2GAuth(BaseAuthProvider):
    """
    G2G auth provider with reactive-only token refresh.

    Tokens start with infinite expiry — no proactive refresh.
    Refresh is triggered externally via the retry/runtime path
    when a 401/403 is encountered.
    """

    def __init__(
        self,
        *,
        transport: BaseHttpTransport,
        base_url: str = "https://sls.g2g.com",
        access_token: str = "",
        refresh_token: str = "",
        active_device_token: str = "",
        long_lived_token: str = "",
        seller_id: str = "",
        logger: SdkLogger | None = None,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._base_url = base_url
        self._access_token = access_token
        self._refresh_token_value = refresh_token
        self._active_device_token = active_device_token
        self._long_lived_token = long_lived_token
        self._seller_id = seller_id
        self._logger = logger or NullLogger()

        # Reactive-only: set effectively infinite expiry if token exists
        if access_token:
            self._expires_at = float("inf")

    @property
    def access_token(self) -> str:
        return self._access_token

    def set_token(self, token: str) -> None:
        """Update the access token and reset to infinite expiry."""
        self._access_token = token
        self._expires_at = float("inf")

    def _do_refresh(self) -> bool:
        """
        Refresh the G2G access token via POST /user/refresh_access.

        Sends a multi-token payload and extracts the new access_token
        from the G2G envelope response.
        """
        url = f"{self._base_url}/user/refresh_access"
        payload = {
            "user_id": self._seller_id,
            "refresh_token": self._refresh_token_value,
            "active_device_token": self._active_device_token,
            "long_lived_token": self._long_lived_token,
        }

        self._logger.info("Refreshing G2G access token")

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                json_body=payload,
                headers=self._build_headers(),
                timeout=30.0,
            )
        except Exception as exc:
            self._logger.warning("G2G token refresh transport error", error=str(exc))
            return False

        if not response.is_success:
            self._logger.warning(
                "G2G token refresh failed",
                status_code=response.status_code,
            )
            return False

        try:
            body = response.json()
            new_token = body.get("payload", {}).get("access_token")
            if not new_token:
                self._logger.warning("G2G token refresh response missing access_token")
                return False

            self._access_token = new_token

            # Update refresh token if returned
            new_refresh = body.get("payload", {}).get("refresh_token")
            if new_refresh:
                self._refresh_token_value = new_refresh

            # Reactive model: set infinite expiry again
            self._expires_at = float("inf")
            self._logger.info("G2G access token refreshed successfully")
            return True

        except Exception as exc:
            self._logger.warning("G2G token refresh parse error", error=str(exc))
            return False

    def _build_headers(self) -> dict[str, str]:
        """Build auth headers with the current access token."""
        headers: dict[str, str] = {}
        if self._access_token:
            headers["authorization"] = self._access_token
        return headers
