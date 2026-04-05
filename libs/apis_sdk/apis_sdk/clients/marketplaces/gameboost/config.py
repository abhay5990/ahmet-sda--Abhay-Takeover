"""
GameBoost client configuration.

Holds connection settings needed for the GameBoost API.
Authentication token is injected separately via BearerTokenAuth.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GameBoostConfig(BaseModel):
    """Configuration for the GameBoost API client."""

    base_url: str = Field(
        default="https://api.gameboost.com/v2",
        description="GameBoost API base URL (v2).",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )

    model_config = {"frozen": True}
