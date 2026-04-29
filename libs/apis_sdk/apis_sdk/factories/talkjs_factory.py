"""
TalkJS client factory.

Creates configured TalkJS service client instances.
"""

from __future__ import annotations

from apis_sdk.clients.services.talkjs.client import TalkJsClient
from apis_sdk.clients.services.talkjs.config import TalkJsConfig
from apis_sdk.clients.services.talkjs.facade import TalkJsFacade


class TalkJsFactory:
    """Factory for creating TalkJS service clients."""

    @staticmethod
    def create(
        *,
        app_id: str,
        user_id: str,
        token: str = "",
        extern_id: str = "",
        origin: str = "https://www.eldorado.gg",
        referer: str = "https://www.eldorado.gg/",
        timeout: float = 30.0,
    ) -> TalkJsFacade:
        config = TalkJsConfig(
            app_id=app_id,
            user_id=user_id,
            extern_id=extern_id,
            origin=origin,
            referer=referer,
            timeout=timeout,
        )
        client = TalkJsClient(config, token=token)
        return TalkJsFacade(client)
