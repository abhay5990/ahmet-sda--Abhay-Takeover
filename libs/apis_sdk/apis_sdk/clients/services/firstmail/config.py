"""
FirstMail client configuration.

All settings needed to connect to the FirstMail API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FirstMailConfig(BaseModel):
    """Configuration for the FirstMail API client."""

    api_key: str = Field(..., min_length=1, description="FirstMail X-API-KEY")
    base_url: str = Field(
        default="https://firstmail.ltd/api/v1",
        description="FirstMail API base URL (override per credential)",
    )
    timeout: float = Field(default=30.0, gt=0, description="Request timeout in seconds")

    model_config = {"frozen": True}
