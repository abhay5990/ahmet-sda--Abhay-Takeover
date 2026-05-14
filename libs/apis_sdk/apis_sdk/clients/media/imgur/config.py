"""
Imgur client configuration.

Holds connection settings for the Imgur API.
The Client-ID is injected separately via the facade.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImgurConfig(BaseModel):
    """Configuration for the Imgur API client."""

    base_url: str = Field(
        default="https://api.imgur.com/3",
        description="Imgur API v3 base URL.",
    )
    public_base_url: str = Field(
        default="https://api.imgur.com/post/v1",
        description="Imgur public post/v1 endpoint base (used for album reads).",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )

    model_config = {"frozen": True}
