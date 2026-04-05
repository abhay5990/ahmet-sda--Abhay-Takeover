"""
GameBoost client factory.

Creates configured GameBoost marketplace client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.auth.bearer import BearerTokenAuth
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import MarketplaceRetryPolicy, RetryPolicy
from apis_sdk.infrastructure.retry.strategy import MarketplaceRetryStrategy, RetryStrategy
from apis_sdk.clients.marketplaces.gameboost.client import GameBoostClient
from apis_sdk.clients.marketplaces.gameboost.config import GameBoostConfig
from apis_sdk.clients.marketplaces.gameboost.facade import GameBoostFacade


class GameBoostFactory:
    """Factory for creating GameBoost marketplace clients."""

    @staticmethod
    def create(
        *,
        token: str = "",
        token_ttl_seconds: float = 86400.0,
        transport: BaseHttpTransport,
        base_url: str = "https://api.gameboost.com/v2",
        timeout: float = 30.0,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> GameBoostFacade:
        """
        Create a fully configured GameBoost facade.

        Args:
            token: Bearer token for API authentication.
            token_ttl_seconds: TTL for the bearer token.
            transport: HTTP transport for API calls.
            base_url: GameBoost API base URL.
            timeout: Request timeout.
            proxy_pool: Optional proxy pool for request routing.
            retry_policy: Optional retry policy. Defaults to MarketplaceRetryPolicy.
            retry_strategy: Optional retry strategy. Defaults to MarketplaceRetryStrategy.
            max_retry_attempts: Retry attempts for retryable operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use GameBoostFacade instance.
        """
        config = GameBoostConfig(
            base_url=base_url,
            timeout=timeout,
        )

        auth = BearerTokenAuth(
            token=token,
            token_ttl_seconds=token_ttl_seconds,
        )

        policy = retry_policy or MarketplaceRetryPolicy()
        strategy = retry_strategy or MarketplaceRetryStrategy()

        client = GameBoostClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return GameBoostFacade(
            client=client,
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=policy,
            retry_strategy=strategy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
        )
