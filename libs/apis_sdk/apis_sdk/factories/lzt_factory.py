"""
LZT Market client factory.

Creates configured LZT Market marketplace client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.auth.bearer import BearerTokenAuth
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import MarketplaceRetryPolicy, RetryPolicy
from apis_sdk.infrastructure.retry.strategy import MarketplaceRetryStrategy, RetryStrategy
from apis_sdk.clients.marketplaces.lzt.client import LztClient
from apis_sdk.clients.marketplaces.lzt.config import LztConfig
from apis_sdk.clients.marketplaces.lzt.facade import LztFacade


class LztFactory:
    """Factory for creating LZT Market marketplace clients."""

    @staticmethod
    def create(
        *,
        token: str = "",
        token_ttl_seconds: float = 86400.0,
        transport: BaseHttpTransport,
        base_url: str = "https://api.lzt.market",
        timeout: float = 30.0,
        rate_limit_delay: float = 0.2,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> LztFacade:
        """
        Create a fully configured LZT Market facade.

        Args:
            token: Bearer token for API authentication.
                   Externally managed — the SDK does NOT refresh
                   or reload tokens from a database.
            token_ttl_seconds: TTL for the bearer token.
            transport: HTTP transport for API calls.
            base_url: LZT Market API base URL.
            timeout: Request timeout.
            rate_limit_delay: Minimum seconds between requests (default 0.2s).
            proxy_pool: Optional proxy pool for request routing.
            retry_policy: Optional retry policy. Defaults to MarketplaceRetryPolicy.
            retry_strategy: Optional retry strategy. Defaults to MarketplaceRetryStrategy.
            max_retry_attempts: Retry attempts for retryable operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use LztFacade instance.
        """
        config = LztConfig(
            base_url=base_url,
            timeout=timeout,
            rate_limit_delay=rate_limit_delay,
        )

        auth = BearerTokenAuth(
            token=token,
            token_ttl_seconds=token_ttl_seconds,
        )

        policy = retry_policy or MarketplaceRetryPolicy()
        strategy = retry_strategy or MarketplaceRetryStrategy()

        client = LztClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return LztFacade(
            client=client,
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=policy,
            retry_strategy=strategy,
            max_retry_attempts=max_retry_attempts,
            rate_limit_delay=rate_limit_delay,
            logger=logger,
        )
