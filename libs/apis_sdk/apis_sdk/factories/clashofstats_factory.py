"""
ClashOfStats client factory.

Creates configured ClashOfStats tracker client instances.
Uses CurlCffiTransport by default since ClashOfStats is
Cloudflare-protected and requires browser TLS fingerprinting.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.clients.trackers.clashofstats.client import ClashOfStatsClient
from apis_sdk.clients.trackers.clashofstats.config import ClashOfStatsConfig
from apis_sdk.clients.trackers.clashofstats.facade import ClashOfStatsFacade


class ClashOfStatsFactory:
    """Factory for creating ClashOfStats tracker clients."""

    @staticmethod
    def create(
        *,
        transport: BaseHttpTransport,
        base_url: str = "https://api.clashofstats.com",
        website_url: str = "https://www.clashofstats.com",
        timeout: float = 15.0,
        proxy_pool: ProxyPool | None = None,
        logger: SdkLogger | None = None,
    ) -> ClashOfStatsFacade:
        """
        Create a fully configured ClashOfStats facade.

        The transport should be a CurlCffiTransport with browser
        impersonation enabled — ClashOfStats is Cloudflare-protected.

        Args:
            transport: HTTP transport (typically CurlCffiTransport).
            base_url: ClashOfStats API base URL.
            website_url: ClashOfStats website URL (for referer header).
            timeout: Request timeout.
            proxy_pool: Optional proxy pool for request routing.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use ClashOfStatsFacade instance.
        """
        config = ClashOfStatsConfig(
            base_url=base_url,
            website_url=website_url,
            timeout=timeout,
        )

        client = ClashOfStatsClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return ClashOfStatsFacade(
            client=client,
            proxy_pool=proxy_pool,
            logger=logger,
        )
