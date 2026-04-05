"""
Eldorado client factory.

Creates configured Eldorado marketplace client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import MarketplaceRetryPolicy, RetryPolicy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy
from apis_sdk.clients.marketplaces.eldorado.auth import EldoradoCognitoAuth
from apis_sdk.clients.marketplaces.eldorado.client import EldoradoClient
from apis_sdk.clients.marketplaces.eldorado.config import EldoradoConfig
from apis_sdk.clients.marketplaces.eldorado.facade import EldoradoFacade
from apis_sdk.clients.marketplaces.eldorado.retry import EldoradoRetryStrategy


class EldoradoFactory:
    """Factory for creating Eldorado marketplace clients."""

    @staticmethod
    def create(
        *,
        email: str = "",
        password: str = "",
        id_token: str = "",
        id_token_ttl_seconds: float = 3600.0,
        enable_cognito_auth: bool = False,
        transport: BaseHttpTransport,
        store_identifier: str = "eldorado_main",
        base_url: str = "https://www.eldorado.gg",
        timeout: float = 30.0,
        cognito_region: str = "us-east-2",
        cognito_user_pool_id: str = "us-east-2_MlnzCFgHk",
        cognito_client_id: str = "1956req5ro9drdtbf5i6kis4la",
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> EldoradoFacade:
        """
        Create a fully configured Eldorado facade.

        Args:
            email: Eldorado account email (required for Cognito mode).
            password: Eldorado account password (required for Cognito mode).
            id_token: Optional pre-fetched Eldorado ID token for pilot mode.
            id_token_ttl_seconds: TTL for id_token mode.
            enable_cognito_auth: Enable Cognito SRP auth flow.
            transport: HTTP transport for API calls.
            store_identifier: Unique store instance identifier.
            base_url: Eldorado API base URL.
            timeout: Request timeout.
            cognito_region: AWS region for Cognito.
            cognito_user_pool_id: Cognito user pool ID.
            cognito_client_id: Cognito client ID.
            proxy_pool: Optional proxy pool for request routing.
            retry_policy: Optional retry policy. Defaults to MarketplaceRetryPolicy.
            retry_strategy: Optional retry strategy. Defaults to EldoradoRetryStrategy.
            max_retry_attempts: Retry attempts for operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use EldoradoFacade instance.
        """
        config = EldoradoConfig(
            email=email,
            password=password,
            base_url=base_url,
            timeout=timeout,
            store_identifier=store_identifier,
            id_token=id_token,
            id_token_ttl_seconds=id_token_ttl_seconds,
            enable_cognito_auth=enable_cognito_auth,
            cognito_region=cognito_region,
            cognito_user_pool_id=cognito_user_pool_id,
            cognito_client_id=cognito_client_id,
        )

        auth = EldoradoCognitoAuth(config=config, logger=logger)
        policy = retry_policy or MarketplaceRetryPolicy()
        strategy = retry_strategy or EldoradoRetryStrategy()

        client = EldoradoClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return EldoradoFacade(
            client=client,
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=policy,
            retry_strategy=strategy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
        )
