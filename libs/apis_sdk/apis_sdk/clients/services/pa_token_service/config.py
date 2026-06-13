"""
PA Token Service client configuration.

Holds connection settings for the PA Token Service running on VDS.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaTokenServiceConfig(BaseModel):
    """Configuration for the PA Token Service."""

    base_url: str = Field(
        default="http://31.57.156.36:8976",
        description="PA Token Service base URL.",
    )
    api_key: str = Field(
        default="pa-s4g-Xk9mT2vL7nQp4wR8jY3bF6hA",
        description="API key for PA Token Service authentication.",
    )
    timeout: float = Field(
        default=300.0,
        gt=0,
        description="Request timeout in seconds (Puppeteer login can take ~100s).",
    )

    model_config = {"frozen": True}
