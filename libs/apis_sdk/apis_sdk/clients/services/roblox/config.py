"""
Roblox public API client configuration.

No authentication required — Roblox user/game endpoints are public.
Proxy support is essential for regions where Roblox is blocked.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RobloxConfig(BaseModel):
    """Configuration for the Roblox public API client."""

    users_base_url: str = Field(
        default="https://users.roblox.com",
        description="Roblox Users API base URL.",
    )
    games_base_url: str = Field(
        default="https://games.roblox.com",
        description="Roblox Games API base URL.",
    )
    timeout: float = Field(
        default=10.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    proxy_url: str | None = Field(
        default=None,
        description="HTTP/SOCKS proxy URL for regions where Roblox is blocked.",
    )

    model_config = {"frozen": True}
