"""
PlayerAuctions authentication provider with reactive token refresh.

Implements a reactive-only model:
- Tokens start with effectively infinite expiry (no proactive refresh)
- Refresh is triggered only via the retry path (401 → strategy → runtime)
- Refresh calls a local Puppeteer-based microservice (PA Token Service)
  that handles browser-based login and returns a fresh JWT

Safety:
- If refresh fails (microservice down, bad credentials, etc.),
  ``_refresh_failed`` flag is set to prevent infinite retry loops.
- Flag resets only when tokens are externally updated via set_tokens().
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apis_sdk.clients.services.pa_token_service import (
    PaTokenServiceClient,
    PaTokenServiceConfig,
)
from apis_sdk.core.enums import ErrorCategory
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

if TYPE_CHECKING:
    from apis_sdk.infrastructure.proxy.pool import ProxyPool


class PlayerAuctionsAuth(BaseAuthProvider):
    """
    PlayerAuctions auth provider with reactive-only token refresh.

    Tokens start with infinite expiry — no proactive refresh.
    Refresh is triggered externally via the retry/runtime path
    when a 401 is encountered. Uses a local Puppeteer microservice
    to obtain fresh tokens via browser-based login.

    Proxy for token refresh is acquired dynamically from the shared
    proxy pool (same group as API requests) instead of a static string.
    """

    def __init__(
        self,
        *,
        transport: BaseHttpTransport,
        username: str = "",
        password: str = "",
        access_token: str = "",
        proxy_pool: ProxyPool | None = None,
        proxy_group: str | None = None,
        token_service_url: str = "http://localhost:8976",
        logger: SdkLogger | None = None,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._username = username
        self._password = password
        self._access_token = access_token
        self._proxy_pool = proxy_pool
        self._proxy_group = proxy_group
        self._logger = logger or NullLogger()
        self._refresh_failed = False

        # Build token service client (reuses the same transport)
        self._token_service = PaTokenServiceClient(
            config=PaTokenServiceConfig(base_url=token_service_url),
            transport=transport,
            logger=logger,
        )

        # Reactive-only: set effectively infinite expiry if token exists
        if access_token:
            self._expires_at = float("inf")

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def access_token(self) -> str:
        return self._access_token

    def set_tokens(self, access_token: str) -> None:
        """Update token externally and reset failure state."""
        self._access_token = access_token
        self._refresh_failed = False
        self._expires_at = float("inf")

    # ------------------------------------------------------------------
    # BaseAuthProvider overrides
    # ------------------------------------------------------------------

    def _do_refresh(self) -> bool:
        """
        Refresh PlayerAuctions token via the local Puppeteer microservice.

        Sends username/password to PA Token Service which performs a
        browser-based login and returns a fresh JWT. On failure, sets
        ``_refresh_failed`` to prevent repeated attempts and stores the
        reason in ``_last_refresh_error`` for upstream diagnostics.
        """
        if self._refresh_failed:
            self._logger.warning(
                "PlayerAuctions token refresh skipped — previous refresh failed. "
                "Call set_tokens() with new credentials to reset."
            )
            return False

        if not self._username or not self._password:
            reason = "No username/password configured for token refresh"
            self._logger.warning(reason)
            self._last_refresh_error = reason
            self._refresh_failed = True
            return False

        self._logger.info("Refreshing PlayerAuctions token via microservice")

        # Acquire proxy from shared pool for token service
        proxy_str = self._acquire_proxy_string()
        self._logger.info(
            "Token refresh proxy selected",
            proxy=proxy_str or "direct (no proxy)",
        )

        result = self._token_service.authenticate(
            username=self._username,
            password=self._password,
            proxy=proxy_str,
        )

        if not result.ok:
            error_cat = result.error.category if result.error else None
            error_msg = result.error.message if result.error else "unknown"

            if error_cat == ErrorCategory.NETWORK:
                reason = f"Token service unreachable: {error_msg}"
            else:
                reason = f"Token refresh failed: {error_msg}"

            self._logger.warning(reason)
            self._last_refresh_error = reason
            self._refresh_failed = True
            return False

        self._access_token = result.data.access_token
        self._expires_at = float("inf")
        self._refresh_failed = False
        self._last_refresh_error = None
        self._logger.info("PlayerAuctions access token refreshed successfully")
        return True

    def _build_headers(self) -> dict[str, str]:
        """Build auth headers for normal API requests."""
        return {"Authorization": f"Bearer {self._access_token}"}

    def _acquire_proxy_string(self) -> str | None:
        """Acquire a proxy from the shared pool, formatted for PA Token Service."""
        if self._proxy_pool is None:
            return None
        proxy = self._proxy_pool.acquire(group=self._proxy_group)
        if proxy is None:
            return None
        parts = [proxy.host, str(proxy.port)]
        if proxy.username and proxy.password:
            parts.extend([proxy.username, proxy.password])
        return ":".join(parts)
