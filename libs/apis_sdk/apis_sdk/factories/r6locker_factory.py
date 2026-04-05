"""
R6Locker client factory.

Creates configured R6Locker tracker client instances.
Uses CurlCffiTransport by default since R6Locker requires
browser TLS fingerprint impersonation.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.clients.trackers.r6locker.client import R6LockerClient
from apis_sdk.clients.trackers.r6locker.config import R6LockerConfig
from apis_sdk.clients.trackers.r6locker.facade import R6LockerFacade


class R6LockerFactory:
    """Factory for creating R6Locker tracker clients."""

    @staticmethod
    def create(
        *,
        transport: BaseHttpTransport,
        base_url: str = "https://r6skins.locker",
        timeout: float = 30.0,
        proxy_pool: ProxyPool | None = None,
        logger: SdkLogger | None = None,
    ) -> R6LockerFacade:
        """
        Create a fully configured R6Locker facade.

        The transport should be a CurlCffiTransport with browser
        impersonation enabled (e.g. "chrome124") — R6Locker is
        behind Cloudflare and rejects non-browser TLS fingerprints.

        Args:
            transport: HTTP transport (typically CurlCffiTransport).
            base_url: R6Locker base URL.
            timeout: Request timeout.
            proxy_pool: Optional proxy pool for request routing.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use R6LockerFacade instance.
        """
        config = R6LockerConfig(
            base_url=base_url,
            timeout=timeout,
        )

        client = R6LockerClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return R6LockerFacade(
            client=client,
            proxy_pool=proxy_pool,
            logger=logger,
        )
