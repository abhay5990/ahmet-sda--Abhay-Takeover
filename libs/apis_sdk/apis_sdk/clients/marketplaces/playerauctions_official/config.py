"""
PlayerAuctions Official Seller API configuration.

Connection settings for the official PA Seller API.
Uses a single base URL (seller-api.playerauctions.com) and
HMAC-SHA256 authentication instead of browser-based JWT.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PAOfficialConfig(BaseModel):
    """Configuration for the PlayerAuctions Official Seller API client."""

    base_url: str = Field(
        default="https://seller-api.playerauctions.com",
        description="Base URL for the official Seller API.",
    )
    api_key: str = Field(
        description="Public API key (from PA API Key Management).",
    )
    secret_key: str = Field(
        description="Secret key for HMAC-SHA256 signing (shown only once at creation).",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    rate_limit_delay: float = Field(
        default=1.0,
        ge=0,
        description="Minimum delay between requests per facade instance (seconds).",
    )

    model_config = {"frozen": True}
