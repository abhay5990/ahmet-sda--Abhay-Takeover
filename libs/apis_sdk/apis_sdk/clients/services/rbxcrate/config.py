"""
RBXCrate client configuration.

Holds connection settings for the RBXCrate API.
The API key is injected separately via ApiKeyAuth.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RbxCrateConfig(BaseModel):
    """Configuration for the RBXCrate API client."""

    base_url: str = Field(
        default="https://rbxcrate.com/api",
        description="RBXCrate API base URL.",
    )
    timeout: float = Field(
        default=15.0,
        gt=0,
        description="Request timeout in seconds.",
    )

    model_config = {"frozen": True}
