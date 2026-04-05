"""
R6Locker client configuration.

Holds connection settings for the R6Locker tracker.
Browser-like headers are required because R6Locker serves a Cloudflare-protected
SPA and expects browser-shaped requests.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class R6LockerConfig(BaseModel):
    """Configuration for the R6Locker tracker client."""

    base_url: str = Field(
        default="https://r6skins.locker",
        description="R6Locker base URL.",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds.",
    )
    default_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="User-Agent header value.",
    )

    def get_default_headers(self) -> dict[str, str]:
        """Browser-like default headers for tracker requests."""
        return {
            "accept": "*/*",
            "accept-language": "tr,en-US;q=0.9,en;q=0.8",
            "user-agent": self.default_user_agent,
            "sec-ch-ua-platform": '"Windows"',
        }

    model_config = {"frozen": True}
