"""
Dropbox client factory.

Creates configured Dropbox media client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.clients.media.dropbox.client import DropboxClient
from apis_sdk.clients.media.dropbox.config import DropboxConfig
from apis_sdk.clients.media.dropbox.facade import DropboxFacade


class DropboxFactory:
    """Factory for creating Dropbox media client instances."""

    @staticmethod
    def create(
        *,
        access_token: str,
        transport: BaseHttpTransport,
        api_base_url: str = "https://api.dropboxapi.com/2",
        content_base_url: str = "https://content.dropboxapi.com/2",
        upload_folder: str = "/media",
        timeout: float = 60.0,
        logger: SdkLogger | None = None,
    ) -> DropboxFacade:
        """
        Create a fully configured Dropbox facade.

        Args:
            access_token: Dropbox OAuth2 access token.
                          Externally managed -- the SDK does NOT handle
                          token refresh or OAuth2 flow.
            transport: HTTP transport for API calls.
            api_base_url: Dropbox RPC API base URL.
            content_base_url: Dropbox content upload base URL.
            upload_folder: Root folder for uploaded media files.
            timeout: Request timeout in seconds.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use DropboxFacade instance.
        """
        config = DropboxConfig(
            api_base_url=api_base_url,
            content_base_url=content_base_url,
            upload_folder=upload_folder,
            timeout=timeout,
        )

        client = DropboxClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return DropboxFacade(
            client=client,
            access_token=access_token,
        )
