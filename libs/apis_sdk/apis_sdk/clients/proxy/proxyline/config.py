"""
Proxyline client configuration.

All settings needed to connect to the Proxyline API.
Validated at construction time via pydantic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProxylineConfig(BaseModel):
    """Configuration for the Proxyline API client."""

    api_key: str = Field(..., min_length=1, description="Proxyline API key")
    base_url: str = Field(
        default="https://panel.proxyline.net/api",
        description="Proxyline API base URL",
    )
    timeout: float = Field(default=15.0, gt=0, description="Request timeout in seconds")
    proxy_group: str = Field(default="", description="Default proxy group assignment")
    prefer_socks5: bool = Field(
        default=False,
        description="Prefer SOCKS5 port over HTTP when both are available",
    )

    model_config = {"frozen": True}
