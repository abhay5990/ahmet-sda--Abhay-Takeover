"""
StatsRoyale client configuration.

Holds connection settings for the StatsRoyale tracker API.
The API runs on Google Cloud Run and does not require Cloudflare
bypass, but expects browser-like headers with origin/referer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StatsRoyaleConfig(BaseModel):
    """Configuration for the StatsRoyale tracker client."""

    base_url: str = Field(
        default="https://stats-royale-api-js-beta-z2msk5bu3q-uk.a.run.app",
        description="StatsRoyale API base URL.",
    )
    website_url: str = Field(
        default="https://statsroyale.com",
        description="StatsRoyale website URL (used for origin/referer headers).",
    )
    timeout: float = Field(
        default=10.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    default_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36 OPR/120.0.0.0"
        ),
        description="User-Agent header value.",
    )

    def get_default_headers(self) -> dict[str, str]:
        """Browser-like default headers for tracker requests."""
        return {
            "accept": "*/*",
            "accept-language": "tr,en-US;q=0.9,en;q=0.8",
            "cache-control": "no-cache",
            "origin": self.website_url,
            "pragma": "no-cache",
            "referer": f"{self.website_url}/",
            "user-agent": self.default_user_agent,
            "sec-ch-ua-platform": '"Windows"',
            "sec-ch-ua-mobile": "?0",
        }

    model_config = {"frozen": True}
