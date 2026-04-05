"""
ImageShack client configuration.

Holds connection settings for the ImageShack API.
The API key is injected separately via the facade.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImageShackConfig(BaseModel):
    """Configuration for the ImageShack API client."""

    base_url: str = Field(
        default="https://api.imageshack.com/v2",
        description="ImageShack API v2 base URL.",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )

    model_config = {"frozen": True}
