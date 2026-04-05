"""
StatsRoyale client factory.

Creates configured StatsRoyale tracker client instances.
RequestsTransport is sufficient since the API runs on Google
Cloud Run without Cloudflare protection.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.clients.trackers.statsroyale.client import StatsRoyaleClient
from apis_sdk.clients.trackers.statsroyale.config import StatsRoyaleConfig
from apis_sdk.clients.trackers.statsroyale.facade import StatsRoyaleFacade


class StatsRoyaleFactory:
    """Factory for creating StatsRoyale tracker clients."""

    @staticmethod
    def create(
        *,
        transport: BaseHttpTransport,
        base_url: str = "https://stats-royale-api-js-beta-z2msk5bu3q-uk.a.run.app",
        website_url: str = "https://statsroyale.com",
        timeout: float = 10.0,
        proxy_pool: ProxyPool | None = None,
        logger: SdkLogger | None = None,
    ) -> StatsRoyaleFacade:
        """
        Create a fully configured StatsRoyale facade.

        Unlike R6Locker and ClashOfStats, StatsRoyale does NOT
        require CurlCffiTransport — RequestsTransport is sufficient.

        Args:
            transport: HTTP transport (RequestsTransport is fine).
            base_url: StatsRoyale API base URL.
            website_url: StatsRoyale website URL (for origin/referer headers).
            timeout: Request timeout.
            proxy_pool: Optional proxy pool for request routing.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use StatsRoyaleFacade instance.
        """
        config = StatsRoyaleConfig(
            base_url=base_url,
            website_url=website_url,
            timeout=timeout,
        )

        client = StatsRoyaleClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return StatsRoyaleFacade(
            client=client,
            proxy_pool=proxy_pool,
            logger=logger,
        )
