"""
LZT Market client configuration.

Holds connection settings needed for the LZT Market API.
Authentication token is injected separately via BearerTokenAuth.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LztConfig(BaseModel):
    """Configuration for the LZT Market API client."""

    base_url: str = Field(
        default="https://prod-api.lzt.market",
        description="LZT Market API base URL.",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    rate_limit_delay: float = Field(
        default=0.2,
        ge=0,
        description="Minimum seconds between requests (instance-level throttle).",
    )

    model_config = {"frozen": True}
