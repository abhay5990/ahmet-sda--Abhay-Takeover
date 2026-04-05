"""
PA Token Service client configuration.

Holds connection settings for the local Puppeteer-based
PlayerAuctions authentication microservice.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaTokenServiceConfig(BaseModel):
    """Configuration for the PA Token Service."""

    base_url: str = Field(
        default="http://localhost:8976",
        description="PA Token Service base URL.",
    )
    timeout: float = Field(
        default=300.0,
        gt=0,
        description="Request timeout in seconds (Puppeteer login can take ~100s).",
    )

    model_config = {"frozen": True}
