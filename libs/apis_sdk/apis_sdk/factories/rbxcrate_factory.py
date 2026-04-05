"""
RBXCrate client factory.

Creates configured RBXCrate service client instances.
"""

from __future__ import annotations

from apis_sdk.infrastructure.auth.api_key import ApiKeyAuth
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.clients.services.rbxcrate.client import RbxCrateClient
from apis_sdk.clients.services.rbxcrate.config import RbxCrateConfig
from apis_sdk.clients.services.rbxcrate.facade import RbxCrateFacade


class RbxCrateFactory:
    """Factory for creating RBXCrate service clients."""

    @staticmethod
    def create(
        *,
        api_key: str = "",
        transport: BaseHttpTransport,
        base_url: str = "https://rbxcrate.com/api",
        timeout: float = 15.0,
        logger: SdkLogger | None = None,
    ) -> RbxCrateFacade:
        """
        Create a fully configured RBXCrate facade.

        Args:
            api_key: API key for authentication (``api-key`` header).
                     Externally managed — the SDK does NOT reload
                     keys from a database.
            transport: HTTP transport for API calls.
            base_url: RBXCrate API base URL.
            timeout: Request timeout in seconds.
            logger: Optional SDK logger.

        Returns:
            Ready-to-use RbxCrateFacade instance.
        """
        config = RbxCrateConfig(
            base_url=base_url,
            timeout=timeout,
        )

        auth = ApiKeyAuth(api_key=api_key)

        client = RbxCrateClient(
            config=config,
            transport=transport,
            logger=logger,
        )

        return RbxCrateFacade(
            client=client,
            auth=auth,
        )
