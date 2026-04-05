"""
G2G client configuration.

Holds connection settings and credential fields needed for the G2G API.
Browser-like headers are included because G2G expects browser-like requests.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class G2GConfig(BaseModel):
    """Configuration for the G2G API client."""

    base_url: str = Field(
        default="https://sls.g2g.com",
        description="G2G API base URL.",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    seller_id: str = Field(
        default="",
        description="G2G seller/user identifier. Used in URL paths and query params.",
    )
    rate_limit_delay: float = Field(
        default=0.5,
        ge=0,
        description="Minimum delay between requests per facade instance (seconds).",
    )
    default_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        description="User-Agent header value.",
    )

    def get_default_headers(self) -> dict[str, str]:
        """Get browser-like default headers (without credentials)."""
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": self.default_user_agent,
            "content-type": "application/json",
        }

    model_config = {"frozen": True}
