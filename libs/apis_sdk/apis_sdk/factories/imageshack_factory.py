"""
ImageShack client factory.

Creates configured ImageShack media client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.clients.media.imageshack.client import ImageShackClient
from apis_sdk.clients.media.imageshack.config import ImageShackConfig
from apis_sdk.clients.media.imageshack.facade import ImageShackFacade


class ImageShackFactory:
    """Factory for creating ImageShack media client instances."""

    @staticmethod
    def create(
        *,
        api_key: str,
        transport: BaseHttpTransport,
        base_url: str = "https://api.imageshack.com/v2",
        timeout: float = 30.0,
        logger: SdkLogger | None = None,
    ) -> ImageShackFacade:
        """
        Create a fully configured ImageShack facade.

        Args:
            api_key: ImageShack API key for authentication.
                     Externally managed -- the SDK does NOT handle
                     config reload or key rotation.
            transport: HTTP transport for API calls.
            base_url: ImageShack API base URL.
            timeout: Request timeout in seconds.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use ImageShackFacade instance.
        """
        config = ImageShackConfig(
            base_url=base_url,
            timeout=timeout,
        )

        client = ImageShackClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return ImageShackFacade(
            client=client,
            api_key=api_key,
        )
