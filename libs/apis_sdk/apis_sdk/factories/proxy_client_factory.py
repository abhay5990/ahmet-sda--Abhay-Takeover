"""
Proxy client factory.

Creates configured proxy provider client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.retry.policy import ExponentialBackoff, RetryPolicy
from apis_sdk.clients.proxy.proxyline.client import ProxylineClient
from apis_sdk.clients.proxy.proxyline.config import ProxylineConfig
from apis_sdk.clients.proxy.proxyline.facade import ProxylineFacade


class ProxyClientFactory:
    """Factory for creating proxy provider clients."""

    @staticmethod
    def create_proxyline(
        *,
        api_key: str,
        transport: BaseHttpTransport,
        base_url: str = "https://panel.proxyline.net/api",
        timeout: float = 15.0,
        proxy_group: str = "",
        prefer_socks5: bool = False,
        retry_policy: RetryPolicy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> ProxylineFacade:
        """
        Create a fully configured Proxyline facade.

        Args:
            api_key: Proxyline API key.
            transport: HTTP transport to use for API calls.
            base_url: Proxyline API base URL.
            timeout: Request timeout.
            proxy_group: Default proxy group assignment.
            prefer_socks5: Default preference for SOCKS5.
            retry_policy: Optional retry policy. Defaults to ExponentialBackoff.
            max_retry_attempts: Max retry attempts for operations.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use ProxylineFacade instance.
        """
        config = ProxylineConfig(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            proxy_group=proxy_group,
            prefer_socks5=prefer_socks5,
        )

        client = ProxylineClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        policy = retry_policy or ExponentialBackoff()

        return ProxylineFacade(
            client=client,
            config=config,
            retry_policy=policy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
        )
