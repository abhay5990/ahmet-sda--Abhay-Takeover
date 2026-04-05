"""
Use case: Refresh proxy pool from providers.

Fetches fresh proxy lists from configured providers and
loads them into the runtime proxy pool.
"""

from __future__ import annotations

from apis_sdk.core.protocols import ProxyPoolRuntime, ProxyProvider
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.application.dto.proxy import ProxyRefreshResult


class RefreshProxyPoolUseCase:
    """
    Refresh the proxy pool from one or more proxy providers.

    This use case:
    1. Fetches proxy lists from each configured provider
    2. Maps them to SDK-canonical ProxyRecords
    3. Loads them into the proxy pool

    Usage:
        use_case = RefreshProxyPoolUseCase(
            pool=proxy_pool,
            providers=[proxyline_facade],
        )
        results = use_case.execute()
    """

    def __init__(
        self,
        pool: ProxyPoolRuntime,
        providers: list[ProxyProvider],
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._pool = pool
        self._providers = providers
        self._logger = logger or NullLogger()

    def execute(self, *, clear_existing: bool = True) -> list[ProxyRefreshResult]:
        """
        Execute the proxy pool refresh.

        Args:
            clear_existing: Whether to clear the pool before loading.
                          Set to False to merge with existing proxies.

        Returns:
            List of ProxyRefreshResult, one per provider.
        """
        if clear_existing:
            self._pool.clear()

        results: list[ProxyRefreshResult] = []

        for provider in self._providers:
            result = self._refresh_from_provider(provider)
            results.append(result)

        self._logger.info(
            "Proxy pool refresh complete",
            total_loaded=self._pool.size,
            healthy=self._pool.healthy_count,
            providers=len(self._providers),
        )

        return results

    def _refresh_from_provider(self, provider: ProxyProvider) -> ProxyRefreshResult:
        """Refresh proxies from a single provider."""
        name = provider.provider_name

        self._logger.info(f"Fetching proxies from {name}")

        api_result = provider.list_proxies()

        if not api_result.ok:
            error_msg = api_result.error.message if api_result.error else "Unknown error"
            self._logger.error(f"Failed to fetch from {name}: {error_msg}")
            return ProxyRefreshResult(
                provider=name,
                fetched=0,
                loaded=0,
                errors=[error_msg],
                success=False,
            )

        proxies = api_result.data or []

        for proxy in proxies:
            self._pool.add(proxy)

        self._logger.info(
            f"Loaded {len(proxies)} proxies from {name}",
            provider=name,
            count=len(proxies),
        )

        return ProxyRefreshResult(
            provider=name,
            fetched=len(proxies),
            loaded=len(proxies),
            success=True,
        )
