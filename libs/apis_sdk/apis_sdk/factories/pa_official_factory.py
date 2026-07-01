"""
PlayerAuctions Official Seller API client factory.

Creates configured PAOfficialFacade instances using HMAC-SHA256 auth.
No token service, no browser login — just API key + secret key.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import MarketplaceRetryPolicy, RetryPolicy
from apis_sdk.infrastructure.retry.strategy import MarketplaceRetryStrategy, RetryStrategy

from apis_sdk.clients.marketplaces.playerauctions_official.auth import PAOfficialAuth
from apis_sdk.clients.marketplaces.playerauctions_official.client import PAOfficialClient
from apis_sdk.clients.marketplaces.playerauctions_official.config import PAOfficialConfig
from apis_sdk.clients.marketplaces.playerauctions_official.facade import PAOfficialFacade


class PAOfficialFactory:
    """Factory for creating PlayerAuctions Official Seller API clients."""

    @staticmethod
    def create(
        *,
        api_key: str,
        secret_key: str,
        transport: BaseHttpTransport,
        base_url: str = "https://seller-api.playerauctions.com",
        timeout: float = 30.0,
        rate_limit_delay: float = 1.0,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> PAOfficialFacade:
        """
        Create a fully configured PAOfficialFacade.

        Args:
            api_key: PA API key (public identifier).
            secret_key: PA secret key (for HMAC-SHA256 signing).
            transport: HTTP transport for API calls.
            base_url: Official Seller API base URL.
            timeout: Request timeout in seconds.
            rate_limit_delay: Min delay between requests (seconds).
            proxy_pool: Optional proxy pool.
            retry_policy: Optional retry policy. Defaults to MarketplaceRetryPolicy.
            retry_strategy: Optional retry strategy. Defaults to MarketplaceRetryStrategy.
            max_retry_attempts: Retry attempts for retryable operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use PAOfficialFacade instance.
        """
        config = PAOfficialConfig(
            base_url=base_url,
            api_key=api_key,
            secret_key=secret_key,
            timeout=timeout,
            rate_limit_delay=rate_limit_delay,
        )

        auth = PAOfficialAuth(api_key=api_key, secret_key=secret_key)

        policy = retry_policy or MarketplaceRetryPolicy()
        strategy = retry_strategy or MarketplaceRetryStrategy()

        client = PAOfficialClient(
            config=config,
            auth=auth,
            transport=transport,
            logger=logger,
        )

        return PAOfficialFacade(
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
