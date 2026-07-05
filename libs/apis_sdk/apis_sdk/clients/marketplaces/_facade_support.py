"""
Shared facade-support utilities for marketplace providers.

Contains:
- ``result_to_exception`` / ``exception_to_result``: mechanical ApiResult ↔
  exception conversions that were duplicated across every marketplace facade.
- ``FacadeExecutor``: internal composed helper that owns the retry/proxy/auth
  orchestration loop.  Facades hold an instance and delegate ``execute_with_retry``
  / ``execute_once`` to it, keeping provider-specific logic in the facade itself.

This module is **internal** to the marketplace clients package.  Nothing outside
``apis_sdk.clients.marketplaces`` should import from here.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.exceptions import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    SdkError,
    TimeoutError,
    TransportError,
    ValidationError,
)
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.infrastructure.retry.runtime import RuntimeRetryStrategy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy

T = TypeVar("T")

# ---------------------------------------------------------------------------
# ApiResult ↔ exception conversion functions
# ---------------------------------------------------------------------------

# Maps HTTP status codes to ErrorCategory for ProviderError round-trips.
# Used by exception_to_result to recover the original category that would
# otherwise be lost when a typed ApiResult passes through raise→catch.
_STATUS_CATEGORY: dict[int, ErrorCategory] = {
    404: ErrorCategory.NOT_FOUND,
    # 403 ProviderError specifically means NOT_FOUND (e.g. LZT "Account deleted").
    # Auth 403s go through AuthenticationError, never reach this path.
    403: ErrorCategory.NOT_FOUND,
    400: ErrorCategory.VALIDATION,
    422: ErrorCategory.VALIDATION,
}

# Type for the narrow provider-specific exception hook.
# Returns an ApiResult if it handled the exception, None to fall through.
ExceptionHook = Callable[[Exception], ApiResult[Any] | None]


def result_to_exception(result: ApiResult[Any], *, fallback_provider: str) -> SdkError:
    """Convert a failed ``ApiResult`` into a typed SDK exception.

    The ``fallback_provider`` is used only when ``result.error.provider``
    is ``None``.  In practice, well-behaved clients always set the provider
    on error details, so the fallback is a safety net.
    """
    error = result.error
    if error is None:
        return ProviderError(
            f"{fallback_provider} operation failed without error details.",
            provider=fallback_provider,
            status_code=result.status_code,
            is_retryable=False,
        )

    provider = error.provider or fallback_provider
    details = dict(error.details)

    if error.category == ErrorCategory.RATE_LIMIT:
        return RateLimitError(
            error.message,
            provider=provider,
            retry_after=error.retry_after,
            details=details,
        )
    if error.category == ErrorCategory.TIMEOUT:
        return TimeoutError(
            error.message,
            provider=provider,
            timeout_seconds=error.retry_after,
            details=details,
        )
    if error.category == ErrorCategory.NETWORK:
        return TransportError(
            error.message,
            provider=provider,
            status_code=error.status_code,
            details=details,
        )
    if error.category == ErrorCategory.AUTHENTICATION:
        return AuthenticationError(
            error.message,
            provider=provider,
            details=details,
        )
    if error.category == ErrorCategory.VALIDATION:
        return ValidationError(
            error.message,
            provider=provider,
            details=details,
        )
    if error.category == ErrorCategory.NOT_FOUND:
        return ProviderError(
            error.message,
            provider=provider,
            status_code=error.status_code,
            is_retryable=False,
            details=details,
        )
    return ProviderError(
        error.message,
        provider=provider,
        status_code=error.status_code,
        is_retryable=error.is_retryable,
        details=details,
    )


def exception_to_result(exc: Exception, *, fallback_provider: str) -> ApiResult[Any]:
    """Convert an exception back into a failed ``ApiResult``.

    Called after retries are exhausted (or on single-attempt paths) so that
    the facade always returns ``ApiResult`` instead of raising.
    """
    if isinstance(exc, RateLimitError):
        return ApiResult.from_error(
            ErrorCategory.RATE_LIMIT,
            str(exc),
            provider=exc.provider,
            retry_after=exc.retry_after,
            is_retryable=True,
            details=exc.details,
        )
    if isinstance(exc, TimeoutError):
        return ApiResult.from_error(
            ErrorCategory.TIMEOUT,
            str(exc),
            provider=exc.provider,
            status_code=exc.status_code,
            is_retryable=True,
            details=exc.details,
        )
    if isinstance(exc, TransportError):
        return ApiResult.from_error(
            ErrorCategory.NETWORK,
            str(exc),
            provider=exc.provider,
            status_code=exc.status_code,
            is_retryable=True,
            details=exc.details,
        )
    if isinstance(exc, AuthenticationError):
        return ApiResult.from_error(
            ErrorCategory.AUTHENTICATION,
            str(exc),
            provider=exc.provider,
            is_retryable=False,
            details=exc.details,
        )
    if isinstance(exc, ValidationError):
        return ApiResult.from_error(
            ErrorCategory.VALIDATION,
            str(exc),
            provider=exc.provider,
            is_retryable=False,
            details=exc.details,
        )
    if isinstance(exc, ProviderError):
        # Preserve the original error category when the status_code gives a
        # clear signal.  Without this, NOT_FOUND (404) round-trips through
        # result→exception→result and becomes SERVER_ERROR — breaking the
        # cleaner's ability to detect deleted items.
        category = ErrorCategory.SERVER_ERROR
        if exc.status_code is not None:
            category = _STATUS_CATEGORY.get(exc.status_code, ErrorCategory.SERVER_ERROR)
        return ApiResult.from_error(
            category,
            str(exc),
            provider=exc.provider,
            status_code=exc.status_code,
            is_retryable=exc.is_retryable,
            details=exc.details,
        )
    return ApiResult.from_error(
        ErrorCategory.UNKNOWN,
        f"Unexpected {fallback_provider} facade error: {exc}",
        provider=fallback_provider,
        is_retryable=False,
    )


# ---------------------------------------------------------------------------
# FacadeExecutor — composed orchestration helper
# ---------------------------------------------------------------------------


class FacadeExecutor:
    """Internal orchestration helper composed into marketplace facades.

    Owns the mechanical retry/proxy/auth wiring that was previously
    duplicated across every facade.  Facades create one instance at
    ``__init__`` time, then delegate ``execute_with_retry`` /
    ``execute_once`` to it.

    **Not part of the public SDK surface.**

    Parameters
    ----------
    auth:
        Auth provider (for ``get_auth_headers`` and legacy refresh path).
    transport:
        HTTP transport (for ``RuntimeRetryStrategy`` session reset).
    proxy_pool:
        Optional proxy pool for proxy acquisition/health reporting.
    retry_policy:
        Optional retry policy (``None`` → single attempt).
    retry_strategy:
        Optional retry strategy (drives session/proxy/auth decisions).
    max_retry_attempts:
        Maximum retry attempts (clamped ≥ 1).
    logger:
        SDK logger instance.
    provider_name:
        Lowercase provider identifier used as fallback in error details
        and log messages (e.g. ``"eldorado"``, ``"gameboost"``, ``"g2g"``).
    pre_execute:
        Optional no-arg callable invoked before every execution attempt
        (both ``execute_with_retry`` and ``execute_once``).  Used by
        providers for per-instance throttling (e.g. G2G, PlayerAuctions).
    exception_hook:
        Optional callable ``(Exception) -> ApiResult | None``.  Called
        before the generic ``exception_to_result`` conversion.  If it
        returns an ``ApiResult``, that result is used; if ``None``, the
        generic path runs.  Used by Eldorado for
        ``EldoradoProviderNotReadyError``.
    """

    def __init__(
        self,
        *,
        auth: BaseAuthProvider,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
        provider_name: str,
        pre_execute: Callable[[], None] | None = None,
        exception_hook: ExceptionHook | None = None,
    ) -> None:
        self._auth = auth
        self._transport = transport
        self._proxy_pool = proxy_pool
        self._retry = retry_policy
        self._retry_strategy = retry_strategy
        self._max_retry_attempts = max(1, max_retry_attempts)
        self._logger = logger or NullLogger()
        self._provider_name = provider_name
        self._pre_execute = pre_execute
        self._exception_hook = exception_hook
        # Sticky proxy: once a proxy is acquired for a group, reuse it until
        # failure.  Keyed by group name (None key = no-group).
        self._sticky_proxy: dict[str | None, ProxyRecord] = {}

    # -- auth helpers -------------------------------------------------------

    def get_auth_headers(self) -> dict[str, str]:
        """Get current auth headers, refreshing token if needed."""
        return self._auth.get_auth_headers()

    # -- proxy helpers ------------------------------------------------------

    def _get_proxy_url(
        self,
        *,
        group: str | None = None,
        _retry_ctx: RuntimeRetryStrategy | None = None,
    ) -> str | None:
        """Acquire a proxy URL from the pool, if available.

        Uses sticky proxy logic: once a proxy is selected for a group it is
        reused for all subsequent requests until a failure triggers rotation.
        During retry flows the retry context's ``exclude_proxy`` forces a
        new acquisition (the failed proxy is skipped).
        """
        if self._proxy_pool is None:
            return None

        exclude = _retry_ctx.exclude_proxy if _retry_ctx is not None else None

        # Try to reuse the sticky proxy for this group
        sticky = self._sticky_proxy.get(group)
        if sticky is not None and sticky is not exclude:
            if self._proxy_pool.is_healthy(sticky):
                if _retry_ctx is not None:
                    _retry_ctx.track_proxy(sticky)
                return sticky.to_url()
            # Sticky proxy is no longer healthy — discard it
            del self._sticky_proxy[group]

        # Acquire a new proxy from the pool
        proxy = self._proxy_pool.acquire(group=group, exclude=exclude)
        if _retry_ctx is not None:
            _retry_ctx.track_proxy(proxy)
        if proxy is None:
            self._logger.info("No proxy available from pool", group=group or "default")
            return None

        # Pin as the sticky proxy for this group
        self._sticky_proxy[group] = proxy
        # Sync to auth provider so token refresh uses the same proxy/IP
        if hasattr(self._auth, 'set_sticky_proxy'):
            self._auth.set_sticky_proxy(proxy)
        self._logger.info(
            "Proxy acquired (sticky)",
            proxy=f"{proxy.host}:{proxy.port}",
            group=group or "default",
        )
        return proxy.to_url()

    def _report_proxy_success(
        self,
        runtime_strategy: RuntimeRetryStrategy | None,
    ) -> None:
        """Report proxy success so health tracker can clear failures."""
        if self._proxy_pool is None or runtime_strategy is None:
            return
        proxy = runtime_strategy.last_proxy
        if proxy is not None:
            self._proxy_pool.report_success(proxy)

    # -- runtime strategy ---------------------------------------------------

    def _build_runtime_strategy(self) -> RuntimeRetryStrategy | None:
        """Create a RuntimeRetryStrategy adapter for one retry execution."""
        if self._retry_strategy is None:
            return None
        return RuntimeRetryStrategy(
            self._retry_strategy,
            auth=self._auth,
            transport=self._transport,
            proxy_pool=self._proxy_pool,
            logger=self._logger,
        )

    # -- result / exception conversion (delegates to module functions) -------

    def _result_to_exception(self, result: ApiResult[Any]) -> SdkError:
        return result_to_exception(result, fallback_provider=self._provider_name)

    def _exception_to_result(self, exc: Exception) -> ApiResult[Any]:
        if self._exception_hook is not None:
            hooked = self._exception_hook(exc)
            if hooked is not None:
                return hooked

        # Enrich auth errors with refresh failure context when available.
        if isinstance(exc, AuthenticationError):
            refresh_error = self._auth.last_refresh_error
            if refresh_error:
                exc.details['refresh_error'] = refresh_error
                exc = AuthenticationError(
                    f"{exc}. {refresh_error}",
                    provider=exc.provider,
                    is_token_expired=exc.is_token_expired,
                    details=exc.details,
                )

        return exception_to_result(exc, fallback_provider=self._provider_name)

    # -- execution paths ----------------------------------------------------

    def execute_with_retry(
        self,
        operation: Callable[[str | None], ApiResult[T]],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[T]:
        """Execute a client call with retry policy when configured.

        ``operation`` receives a ``proxy_url`` argument so the retry
        loop can manage proxy acquisition (with exclusion) per attempt.

        When a RetryStrategy is provided, it drives the retry decision:
        the strategy decides *what* to do (new session, new proxy, auth
        refresh) and the policy decides *when* (backoff timing).

        Without a strategy, falls back to the legacy path where the
        policy's ``should_retry()`` is the sole decision maker and
        auth refresh is handled inline.
        """
        if self._pre_execute is not None:
            self._pre_execute()

        if self._retry is None:
            try:
                proxy_url = self._get_proxy_url(group=proxy_group)
                return operation(proxy_url)
            except Exception as exc:
                return self._exception_to_result(exc)

        runtime_strategy = self._build_runtime_strategy()

        def wrapped() -> ApiResult[T]:
            proxy_url = self._get_proxy_url(
                group=proxy_group,
                _retry_ctx=runtime_strategy,
            )
            result = operation(proxy_url)
            if result.ok:
                self._report_proxy_success(runtime_strategy)
                return result
            exc = self._result_to_exception(result)
            # Legacy path: inline auth refresh when no strategy is provided
            if runtime_strategy is None and isinstance(exc, AuthenticationError):
                try:
                    self._auth.refresh()
                except Exception as refresh_exc:
                    self._logger.warning(
                        "Auth refresh failed during retry",
                        error=str(refresh_exc),
                    )
            raise exc

        try:
            return self._retry.execute(
                wrapped,
                max_attempts=self._max_retry_attempts,
                strategy=runtime_strategy,
            )
        except Exception as exc:
            self._logger.warning(
                f"{self._provider_name} operation exhausted retries",
                error=str(exc),
            )
            return self._exception_to_result(exc)

    def execute_once(
        self,
        operation: Callable[[str | None], ApiResult[T]],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[T]:
        """Execute a client call once, with a single auth-retry on 401.

        Used for non-idempotent operations (e.g. POST create_offer).
        No general retry to prevent duplicates, but a 401 means the
        request was rejected (not processed), so refreshing auth and
        retrying once is safe.
        """
        if self._pre_execute is not None:
            self._pre_execute()

        try:
            proxy_url = self._get_proxy_url(group=proxy_group)
            result = operation(proxy_url)
        except Exception as exc:
            return self._exception_to_result(exc)

        # If auth error (401/403), try refresh + one retry
        if not result.ok and result.error and result.error.category == ErrorCategory.AUTHENTICATION:
            self._logger.info("Auth failed on write operation, attempting token refresh")
            try:
                self._auth.refresh()
            except Exception as exc:
                self._logger.warning("Auth refresh failed", error=str(exc))
                return self._exception_to_result(
                    AuthenticationError(
                        f"Auth refresh failed: {exc}",
                        provider=self._provider_name,
                    )
                )

            # Retry once with refreshed auth
            self._logger.info("Retrying write operation after auth refresh")
            if self._pre_execute is not None:
                self._pre_execute()
            try:
                result = operation(proxy_url)
            except Exception as exc:
                return self._exception_to_result(exc)

        return result
