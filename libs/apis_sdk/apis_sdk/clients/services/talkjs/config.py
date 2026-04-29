"""
TalkJS client configuration.

Holds connection and identity settings for the TalkJS API.
The auth token (boken) is injected separately.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TalkJsConfig(BaseModel):
    """Configuration for the TalkJS API client."""

    app_id: str = Field(description="TalkJS application ID.")
    user_id: str = Field(description="TalkJS internal user ID.")
    extern_id: str = Field(
        default="",
        description="External user ID (e.g. auth0|...).",
    )
    origin: str = Field(
        default="https://www.eldorado.gg",
        description="Origin header for requests.",
    )
    referer: str = Field(
        default="https://www.eldorado.gg/",
        description="Referer header for requests.",
    )
    timeout: float = Field(default=30.0, gt=0)

    model_config = {"frozen": True}
