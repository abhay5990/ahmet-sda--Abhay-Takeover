"""
Proxyline high-level facade.

Provides a clean, consumer-facing API that combines:
- The low-level ProxylineClient (API calls)
- The ProxylineMapper (response mapping)
- Optional retry policy
- Error normalization

This is the primary entry point for consumers using Proxyline.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.exceptions import ProviderError, RateLimitError, TransportError
from apis_sdk.core.models import ProxyRecord
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.clients.proxy.proxyline.config import ProxylineConfig
from apis_sdk.clients.proxy.proxyline.mapper import ProxylineMapper
from apis_sdk.clients.proxy.proxyline.models import (
    ProxylineBalance,
    ProxylineOrder,
    ProxylineProxy,
)

T = TypeVar("T")


class ProxylineApiClient(Protocol):
    def list_proxies(self) -> ApiResult[list[ProxylineProxy]]:
        ...

    def get_balance(self) -> ApiResult[ProxylineBalance]:
        ...

    def get_orders(self) -> ApiResult[list[ProxylineOrder]]:
        ...


class ProxylineFacade:
    """
    High-level interface for the Proxyline proxy provider.

    Coordinates:
    - Low-level API calls via ProxylineClient
    - Response mapping to SDK-canonical ProxyRecord
    - Optional retry with configurable policy
    - Config-driven defaults (group, prefer_socks5)

    Usage:
        facade = ProxylineFacade(client=proxyline_client, config=config)
        result = facade.list_proxies()
        if result.ok:
            for proxy in result.data:
                print(proxy.to_url())
    """

    def __init__(
        self,
        client: ProxylineApiClient,
        *,
        config: ProxylineConfig | None = None,
        retry_policy: RetryPolicy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._retry = retry_policy
        self._max_retry_attempts = max(1, max_retry_attempts)
        self._logger = logger or NullLogger()

    @property
    def provider_name(self) -> str:
        return "proxyline"

    def list_proxies(
        self,
        *,
        group: str | None = None,
        prefer_socks5: bool | None = None,
    ) -> ApiResult[list[ProxyRecord]]:
        """
        Fetch proxies from Proxyline and map to SDK-canonical ProxyRecords.

        Args:
            group: Group label to assign. Falls back to config.proxy_group.
            prefer_socks5: Whether to prefer SOCKS5. Falls back to config.prefer_socks5.

        Returns:
            ApiResult containing a list of ProxyRecord instances.
        """
        effective_group = group if group is not None else (self._config.proxy_group if self._config else "")
        effective_socks5 = prefer_socks5 if prefer_socks5 is not None else (self._config.prefer_socks5 if self._config else False)

        def operation() -> ApiResult[list[ProxyRecord]]:
            result = self._client.list_proxies()

            if not result.ok:
                if result.error is None:
                    return ApiResult.from_error(
                        category=ErrorCategory.UNKNOWN,
                        message="Proxyline provider returned a failure without error detail.",
                        provider=self.provider_name,
                        status_code=result.status_code,
                    )
                return ApiResult.failure(result.error, status_code=result.status_code)

            records = ProxylineMapper.to_proxy_records(
                result.data or [],
                group=effective_group,
                prefer_socks5=effective_socks5,
            )

            self._logger.info(
                "Mapped Proxyline proxies to ProxyRecords",
                raw_count=len(result.data or []),
                active_count=len(records),
                group=effective_group,
            )

            return ApiResult.success(records, status_code=result.status_code)

        return self._execute_with_retry(operation)

    def get_balance(self) -> ApiResult[ProxylineBalance]:
        """Fetch the current Proxyline account balance."""
        return self._execute_with_retry(self._client.get_balance)

    def get_orders(self) -> ApiResult[list[ProxylineOrder]]:
        """Fetch active proxy orders/subscriptions."""
        return self._execute_with_retry(self._client.get_orders)

    def _execute_with_retry(self, operation: Callable[[], ApiResult[T]]) -> ApiResult[T]:
        """Execute an operation with optional retry policy.

        Converts failed ApiResults to exceptions so the retry policy
        can evaluate them. The policy (not the facade) decides what
        is retryable.
        """
        if self._retry is None:
            return operation()

        def wrapped() -> ApiResult[T]:
            result = operation()
            if result.ok:
                return result
            # Convert to typed exception for retry policy evaluation
            error = result.error
            if error is not None:
                if error.category == ErrorCategory.RATE_LIMIT:
                    raise RateLimitError(error.message, provider="proxyline", retry_after=error.retry_after)
                if error.category == ErrorCategory.NETWORK:
                    raise TransportError(error.message, provider="proxyline")
                raise ProviderError(
                    error.message,
                    provider="proxyline",
                    status_code=error.status_code,
                    is_retryable=error.is_retryable,
                )
            raise ProviderError(
                "Proxyline operation failed without error details.",
                provider="proxyline",
                is_retryable=False,
            )

        try:
            return self._retry.execute(wrapped, max_attempts=self._max_retry_attempts)
        except Exception as exc:
            self._logger.warning("Proxyline operation exhausted retries", error=str(exc))
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                str(exc),
                provider="proxyline",
                is_retryable=False,
            )
