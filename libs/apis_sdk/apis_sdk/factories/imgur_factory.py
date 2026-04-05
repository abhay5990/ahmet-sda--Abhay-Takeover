"""
Imgur client factory.

Creates configured Imgur media client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.clients.media.imgur.client import ImgurClient
from apis_sdk.clients.media.imgur.config import ImgurConfig
from apis_sdk.clients.media.imgur.facade import ImgurFacade


class ImgurFactory:
    """Factory for creating Imgur media client instances."""

    @staticmethod
    def create(
        *,
        client_id: str,
        transport: BaseHttpTransport,
        base_url: str = "https://api.imgur.com/3",
        timeout: float = 30.0,
        logger: SdkLogger | None = None,
    ) -> ImgurFacade:
        """
        Create a fully configured Imgur facade.

        Args:
            client_id: Imgur Client-ID for authentication.
                       Externally managed -- the SDK does NOT handle
                       multi-client rotation or config reload.
            transport: HTTP transport for API calls.
            base_url: Imgur API base URL.
            timeout: Request timeout in seconds.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use ImgurFacade instance.
        """
        config = ImgurConfig(
            base_url=base_url,
            timeout=timeout,
        )

        client = ImgurClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return ImgurFacade(
            client=client,
            client_id=client_id,
        )
