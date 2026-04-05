"""
G2G client factory.

Creates configured G2G marketplace client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import MarketplaceRetryPolicy, RetryPolicy
from apis_sdk.infrastructure.retry.strategy import MarketplaceRetryStrategy, RetryStrategy
from apis_sdk.clients.marketplaces.g2g.auth import G2GAuth
from apis_sdk.clients.marketplaces.g2g.client import G2GClient
from apis_sdk.clients.marketplaces.g2g.config import G2GConfig
from apis_sdk.clients.marketplaces.g2g.facade import G2GFacade


class G2GFactory:
    """Factory for creating G2G marketplace clients."""

    @staticmethod
    def create(
        *,
        transport: BaseHttpTransport,
        access_token: str = "",
        refresh_token: str = "",
        active_device_token: str = "",
        long_lived_token: str = "",
        seller_id: str = "",
        base_url: str = "https://sls.g2g.com",
        timeout: float = 30.0,
        rate_limit_delay: float = 0.5,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> G2GFacade:
        """
        Create a fully configured G2G facade.

        Args:
            transport: HTTP transport for API calls (shared with auth).
            access_token: G2G access token.
            refresh_token: G2G refresh token for auth refresh flow.
            active_device_token: G2G device token for auth refresh flow.
            long_lived_token: G2G long-lived token for auth refresh flow.
            seller_id: G2G seller/user identifier.
            base_url: G2G API base URL.
            timeout: Request timeout.
            rate_limit_delay: Minimum delay between requests (seconds).
            proxy_pool: Optional proxy pool for request routing.
            retry_policy: Optional retry policy. Defaults to MarketplaceRetryPolicy.
            retry_strategy: Optional retry strategy. Defaults to MarketplaceRetryStrategy.
            max_retry_attempts: Retry attempts for retryable operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use G2GFacade instance.
        """
        config = G2GConfig(
            base_url=base_url,
            timeout=timeout,
            seller_id=seller_id,
            rate_limit_delay=rate_limit_delay,
        )

        auth = G2GAuth(
            transport=transport,
            base_url=base_url,
            access_token=access_token,
            refresh_token=refresh_token,
            active_device_token=active_device_token,
            long_lived_token=long_lived_token,
            seller_id=seller_id,
            logger=logger,
        )

        policy = retry_policy or MarketplaceRetryPolicy()
        strategy = retry_strategy or MarketplaceRetryStrategy()

        client = G2GClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return G2GFacade(
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
