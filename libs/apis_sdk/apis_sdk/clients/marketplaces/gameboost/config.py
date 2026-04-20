"""
GameBoost client configuration.

Holds connection settings needed for the GameBoost API.
Authentication token is injected separately via BearerTokenAuth.

API notes:
- Max per_page for list endpoints is 50
- Status filter param format: filter[status]=listed (not status=listed)
- Rate limit headers are NOT returned in responses
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
