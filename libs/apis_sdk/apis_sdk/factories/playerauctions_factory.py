"""
PlayerAuctions client factory.

Creates configured PlayerAuctions marketplace client instances.

Auth:
    Uses PlayerAuctionsAuth with reactive token refresh. When a 401 is
    encountered, the retry path triggers _do_refresh() which calls a
    local Puppeteer-based microservice (PA Token Service) to perform
    browser-based login and obtain a fresh JWT.

    If refresh fails (microservice down, bad credentials, etc.), a
    _refresh_failed flag prevents infinite retry loops. Call
    auth.set_tokens() with a new token to reset.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import MarketplaceRetryPolicy, RetryPolicy
from apis_sdk.infrastructure.retry.strategy import MarketplaceRetryStrategy, RetryStrategy
from apis_sdk.clients.marketplaces.playerauctions.auth import PlayerAuctionsAuth
from apis_sdk.clients.marketplaces.playerauctions.client import PlayerAuctionsClient
from apis_sdk.clients.marketplaces.playerauctions.config import PlayerAuctionsConfig
from apis_sdk.clients.marketplaces.playerauctions.facade import PlayerAuctionsFacade


class PlayerAuctionsFactory:
    """Factory for creating PlayerAuctions marketplace clients."""

    @staticmethod
    def create(
        *,
        username: str = "",
        password: str = "",
        access_token: str = "",
        transport: BaseHttpTransport,
        offer_base_url: str = "https://offer-api.playerauctions.com",
        order_base_url: str = "https://order-api.playerauctions.com",
        token_service_url: str = "http://localhost:8976",
        timeout: float = 30.0,
        rate_limit_delay: float = 1.0,
        proxy_pool: ProxyPool | None = None,
        proxy_group: str | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> PlayerAuctionsFacade:
        """
        Create a fully configured PlayerAuctions facade.

        Args:
            username: PlayerAuctions username (for token refresh via microservice).
            password: PlayerAuctions password (for token refresh via microservice).
            access_token: Bearer access token for API authentication.
            transport: HTTP transport for API calls.
            offer_base_url: Base URL for offer/game endpoints.
            order_base_url: Base URL for order endpoints.
            token_service_url: PA Token Service microservice URL.
            timeout: Request timeout in seconds.
            rate_limit_delay: Minimum delay between requests (seconds).
            proxy_pool: Optional proxy pool for request and token refresh routing.
            proxy_group: Proxy group for pool acquisition (token refresh + requests).
            retry_policy: Optional retry policy. Defaults to MarketplaceRetryPolicy.
            retry_strategy: Optional retry strategy. Defaults to MarketplaceRetryStrategy.
            max_retry_attempts: Retry attempts for retryable operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use PlayerAuctionsFacade instance.
        """
        config = PlayerAuctionsConfig(
            offer_base_url=offer_base_url,
            order_base_url=order_base_url,
            timeout=timeout,
            rate_limit_delay=rate_limit_delay,
        )

        auth = PlayerAuctionsAuth(
            transport=transport,
            username=username,
            password=password,
            access_token=access_token,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
            token_service_url=token_service_url,
            logger=logger,
        )

        policy = retry_policy or MarketplaceRetryPolicy()
        strategy = retry_strategy or MarketplaceRetryStrategy()

        client = PlayerAuctionsClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return PlayerAuctionsFacade(
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
