"""
ClashOfStats client configuration.

Holds connection settings for the ClashOfStats tracker.
ClashOfStats is Cloudflare-protected and requires browser-like
TLS fingerprinting to avoid challenge pages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClashOfStatsConfig(BaseModel):
    """Configuration for the ClashOfStats tracker client."""

    base_url: str = Field(
        default="https://api.clashofstats.com",
        description="ClashOfStats API base URL.",
    )
    website_url: str = Field(
        default="https://www.clashofstats.com",
        description="ClashOfStats website URL (used for referer header).",
    )
    timeout: float = Field(
        default=15.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    default_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
        description="User-Agent header value.",
    )

    def get_default_headers(self) -> dict[str, str]:
        """Browser-like default headers for tracker requests."""
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "tr,en-US;q=0.9,en;q=0.8",
            "referer": f"{self.website_url}/",
            "user-agent": self.default_user_agent,
            "sec-ch-ua-platform": '"Windows"',
            "sec-ch-ua-mobile": "?0",
        }

    model_config = {"frozen": True}
