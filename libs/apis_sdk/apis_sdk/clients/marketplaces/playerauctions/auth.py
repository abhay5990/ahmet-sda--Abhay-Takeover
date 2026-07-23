"""
PlayerAuctions authentication provider with reactive token refresh.

Implements a reactive-only model:
- Tokens start with effectively infinite expiry (no proactive refresh)
- Refresh is triggered only via the retry path (401 → strategy → runtime)
- Refresh calls the PA Relay at http://35.231.166.148:3001 to obtain
  a fresh JWT via /pa-access-token (cache-first, browser-based if cold)

Safety:
- If refresh fails (service down, bad credentials, etc.),
  ``_refresh_failed`` flag is set to prevent infinite retry loops.
- Flag resets only when tokens are externally updated via set_tokens().
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from apis_sdk.clients.services.pa_relay import (
    PaRelayClient,
    PaRelayConfig,
)
from apis_sdk.core.enums import ErrorCategory
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

if TYPE_CHECKING:
    from apis_sdk.core.models import ProxyRecord
    from apis_sdk.infrastructure.proxy.pool import ProxyPool


class PlayerAuctionsAuth(BaseAuthProvider):
    """
    PlayerAuctions auth provider with reactive-only token refresh.

    Tokens start with infinite expiry — no proactive refresh.
    Refresh is triggered externally via the retry/runtime path
    when a 401 is encountered. Uses the PA Token Service on VDS
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
        cookie: str = "",
        user_agent: str = "",
        proxy_pool: ProxyPool | None = None,
        proxy_group: str | None = None,
        relay_url: str = "http://35.231.166.148:3001",
        relay_secret: str = "pa-relay-secret-2026",
        store_slug: str = "",
        on_refresh: Callable[[str, str, str], None] | None = None,
        logger: SdkLogger | None = None,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._username = username
        self._password = password
        self._access_token = access_token
        self._cookie = cookie
        self._user_agent = user_agent
        self._proxy_pool = proxy_pool
        self._proxy_group = proxy_group
        self._on_refresh = on_refresh
        self._logger = logger or NullLogger()
        self._refresh_failed = False
        self._transient_backoff_until: float = 0.0
        self._transient_fail_count: int = 0
        self._sticky_proxy: ProxyRecord | None = None
        self._store_slug = store_slug

        # Build PA Relay client for token refresh
        self._relay_client = PaRelayClient(
            config=PaRelayConfig(
                base_url=relay_url,
                relay_secret=relay_secret,
            ),
            transport=transport,
            logger=logger,
        )

        # Token + cookie both present → session is valid, infinite expiry.
        # Token exists but cookie missing → session incomplete, force
        # proactive refresh on first use so we get a complete set.
        if access_token and cookie:
            self._expires_at = float("inf")
        elif access_token and not cookie:
            self._logger.info(
                "PA token exists but cookie missing — will refresh on first use"
            )
            # _expires_at stays at 0.0 → is_expired=True → triggers _do_refresh

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def cookie(self) -> str:
        return self._cookie

    @property
    def user_agent(self) -> str:
        return self._user_agent

    def reset_failure(self) -> None:
        """Reset the refresh-failed flag so the next 401 can retry.

        Call this at the start of each sync run so transient failures
        (network blip, service restart) don't permanently block refresh.
        """
        self._refresh_failed = False
        self._last_refresh_error = None
        self._transient_backoff_until = 0.0
        self._transient_fail_count = 0

    def set_sticky_proxy(self, proxy: ProxyRecord) -> None:
        """Sync the auth sticky proxy with the facade's sticky proxy.

        Called by FacadeExecutor when it pins a new proxy for the group,
        so token refresh uses the same exit IP as API requests.
        """
        self._sticky_proxy = proxy

    def set_tokens(
        self,
        access_token: str,
        *,
        cookie: str = "",
        user_agent: str = "",
    ) -> None:
        """Update token and session data externally, reset failure state."""
        self._access_token = access_token
        if cookie:
            self._cookie = cookie
        if user_agent:
            self._user_agent = user_agent
        self._refresh_failed = False
        self._expires_at = float("inf")

    # ------------------------------------------------------------------
    # BaseAuthProvider overrides
    # ------------------------------------------------------------------

    def refresh(self) -> bool:
        """Force a non-cached relay refresh after a PA 401/403 response.

        ``BaseAuthProvider.get_auth_headers`` still uses the cache-first
        ``_do_refresh()`` path for an incomplete initial session.  The facade
        calls this method only after the marketplace rejects a request, so a
        fresh browser session is required instead of replaying the same cached
        token and cookie.
        """
        with self._lock:
            return self._do_refresh(force_refresh=True)

    # Transient error categories — these should NOT permanently block refresh
    _TRANSIENT_CATEGORIES = frozenset({
        ErrorCategory.NETWORK,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.TIMEOUT,
    })

    # Max consecutive transient failures before giving up for the run
    _MAX_TRANSIENT_FAILURES = 3

    # Backoff seconds per transient failure (multiplied by fail count)
    _TRANSIENT_BACKOFF_STEP = 30

    def _do_refresh(self, *, force_refresh: bool = False) -> bool:
        """
        Refresh PlayerAuctions token via the PA Token Service on VDS.

        ``force_refresh`` bypasses the relay's cached session after an
        authorization rejection from the PlayerAuctions order API.

        Sends username/password to PA Token Service which performs a
        browser-based login and returns a fresh JWT.

        Permanent failures (bad credentials) set ``_refresh_failed`` to
        prevent infinite retries. Transient failures (504, 429, network)
        use a backoff cooldown — the next attempt is allowed after the
        cooldown expires, up to ``_MAX_TRANSIENT_FAILURES`` consecutive
        transient failures.
        """
        if self._refresh_failed:
            self._logger.warning(
                "PlayerAuctions token refresh skipped — credentials invalid. "
                "Call set_tokens() with new credentials to reset."
            )
            return False

        # Transient backoff: skip if cooldown hasn't elapsed
        now = time.monotonic()
        if now < self._transient_backoff_until:
            remaining = int(self._transient_backoff_until - now)
            self._logger.info(
                "Token refresh cooling down — retry in %ds", remaining,
            )
            return False

        if not self._username or not self._password:
            reason = "No username/password configured for token refresh"
            self._logger.warning(reason)
            self._last_refresh_error = reason
            self._refresh_failed = True
            return False

        self._logger.info(
            "Refreshing PlayerAuctions token via relay "
            f"(forced={force_refresh})"
        )

        result = self._relay_client.get_token(
            username=self._username,
            password=self._password,
            store=self._store_slug or self._username,
            force_refresh=force_refresh,
        )

        if not result.ok:
            error_cat = result.error.category if result.error else None
            error_msg = result.error.message if result.error else "unknown"

            if error_cat in self._TRANSIENT_CATEGORIES:
                # Network errors likely mean the proxy is bad — rotate it
                if error_cat == ErrorCategory.NETWORK and self._sticky_proxy is not None:
                    self._proxy_pool.report_failure(self._sticky_proxy)
                    self._sticky_proxy = None

                # Transient: allow retry after backoff
                self._transient_fail_count += 1
                if self._transient_fail_count >= self._MAX_TRANSIENT_FAILURES:
                    reason = (
                        f"Token refresh gave up after {self._transient_fail_count} "
                        f"transient failures: {error_msg}"
                    )
                    self._logger.warning(reason)
                    self._last_refresh_error = reason
                    self._refresh_failed = True
                    return False

                backoff = self._TRANSIENT_BACKOFF_STEP * self._transient_fail_count
                self._transient_backoff_until = time.monotonic() + backoff
                reason = (
                    f"Token refresh transient error ({self._transient_fail_count}/"
                    f"{self._MAX_TRANSIENT_FAILURES}): {error_msg} — "
                    f"will retry after {backoff}s"
                )
                self._logger.warning(reason)
                self._last_refresh_error = reason
                return False

            # Permanent failure (AUTHENTICATION, etc.)
            reason = f"Token refresh failed (permanent): {error_msg}"
            self._logger.warning(reason)
            self._last_refresh_error = reason
            self._refresh_failed = True
            return False

        self._access_token = result.data.access_token
        # Adopt the relay's fresh cookie so direct order-api calls send a
        # matching Bearer + Cookie (a refreshed JWT paired with a stale cookie
        # is rejected with 401). When the relay omits a cookie, keep the
        # existing one rather than clearing it.
        relay_cookie = getattr(result.data, "cookie", "") or ""
        if relay_cookie:
            self._cookie = relay_cookie
        relay_user_agent = getattr(result.data, "user_agent", "") or ""
        if relay_user_agent:
            self._user_agent = relay_user_agent
        self._expires_at = float("inf")
        self._refresh_failed = False
        self._last_refresh_error = None
        self._transient_fail_count = 0
        self._transient_backoff_until = 0.0
        self._logger.info(
            "PlayerAuctions access token refreshed via relay "
            f"(cached={result.data.cached}, forced={force_refresh})"
        )

        # Notify caller (e.g. persist to DB)
        if self._on_refresh is not None:
            try:
                self._on_refresh(
                    self._access_token,
                    self._cookie,
                    self._user_agent,
                )
            except Exception as exc:
                self._logger.warning(
                    "on_refresh callback failed (token still usable)",
                    error=str(exc),
                )

        return True

    def _build_headers(self) -> dict[str, str]:
        """Build auth headers for normal API requests.

        Includes Authorization, Cookie, and User-Agent from the token
        service session. These must match the browser fingerprint used
        during authentication to satisfy Cloudflare checks.
        """
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._access_token}",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        return headers

    def _acquire_proxy_string(self) -> str | None:
        """Proxy acquisition — not used by relay (relay handles proxies internally)."""
        return None
