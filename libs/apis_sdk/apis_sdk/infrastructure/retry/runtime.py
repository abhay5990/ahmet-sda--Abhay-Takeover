"""
Runtime retry strategy adapter.

Wraps a user-provided RetryStrategy and executes runtime actions
(session reset, proxy rotation, auth refresh) in response to retry
decisions. This is the bridge between strategy *decisions* and
actual *runtime side effects*.

Used by marketplace facades to inject their runtime references
into the retry loop without the strategy itself knowing about
sessions, proxies, or auth providers.
"""

from __future__ import annotations

from apis_sdk.core.models import ProxyRecord
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.decision import RetryDecision
from apis_sdk.infrastructure.retry.strategy import RetryStrategy


class RuntimeRetryStrategy(RetryStrategy):
    """
    Wraps a user-provided RetryStrategy and executes runtime actions.

    This is an internal adapter that connects strategy decisions to
    actual runtime behavior (session reset, proxy rotation, auth refresh).
    Facades create this to inject their own runtime references into
    the strategy's on_before_retry() hook.

    Also tracks the last-acquired proxy so that on ``needs_new_proxy``
    the failed proxy can be reported and excluded from the next acquire.
    """

    def __init__(
        self,
        inner: RetryStrategy,
        *,
        auth: BaseAuthProvider,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        logger: SdkLogger | None = None,
    ) -> None:
        self._inner = inner
        self._auth = auth
        self._transport = transport
        self._proxy_pool = proxy_pool
        self._logger = logger or NullLogger()
        self._last_proxy: ProxyRecord | None = None
        self._exclude_proxy: ProxyRecord | None = None

    def track_proxy(self, proxy: ProxyRecord | None) -> None:
        """Record the proxy that was just acquired for the current attempt."""
        self._last_proxy = proxy

    @property
    def last_proxy(self) -> ProxyRecord | None:
        """The proxy used in the most recent attempt, if any."""
        return self._last_proxy

    @property
    def exclude_proxy(self) -> ProxyRecord | None:
        """Proxy to exclude from the next acquire, if any."""
        return self._exclude_proxy

    def decide(self, attempt: int, error: Exception) -> RetryDecision:
        return self._inner.decide(attempt, error)

    def on_before_retry(self, attempt: int, decision: RetryDecision) -> None:
        # Let inner strategy do its own prep first
        self._inner.on_before_retry(attempt, decision)

        if decision.needs_auth_refresh:
            self._logger.info("Refreshing auth before retry", attempt=attempt)
            try:
                self._auth.refresh()
            except Exception as exc:
                self._logger.warning("Auth refresh failed during retry", error=str(exc))

        if decision.needs_new_session and self._transport is not None:
            self._logger.info("Resetting HTTP session before retry", attempt=attempt)
            self._transport.reset_session()

        if decision.needs_new_proxy and self._proxy_pool is not None:
            if self._last_proxy is not None:
                self._logger.info(
                    "Reporting proxy failure and excluding from next acquire",
                    proxy=f"{self._last_proxy.host}:{self._last_proxy.port}",
                    attempt=attempt,
                )
                self._proxy_pool.report_failure(self._last_proxy)
                self._exclude_proxy = self._last_proxy
            else:
                self._logger.info(
                    "Will acquire new proxy on next attempt",
                    attempt=attempt,
                )
