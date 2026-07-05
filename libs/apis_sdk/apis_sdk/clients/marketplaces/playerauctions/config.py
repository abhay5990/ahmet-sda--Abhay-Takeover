"""
PlayerAuctions client configuration.

Holds connection settings for the PlayerAuctions API.
PlayerAuctions uses two separate API hosts — one for offer operations
and one for order operations — so both are configured here.

Browser-like headers are included because PlayerAuctions expects
browser-like requests.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlayerAuctionsConfig(BaseModel):
    """Configuration for the PlayerAuctions API client."""

    offer_base_url: str = Field(
        default="https://offer-api.playerauctions.com",
        description="Base URL for offer and game endpoints.",
    )
    order_base_url: str = Field(
        default="https://order-api.playerauctions.com",
        description="Base URL for order endpoints.",
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
    default_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        description="User-Agent header value.",
    )

    def get_default_headers(self) -> dict[str, str]:
        """Get browser-like default headers (without credentials).

        These are the static headers that mimic a real browser session.
        User-Agent is included as a fallback but will be overridden by
        the auth provider's session-specific User-Agent when available.
        """
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": (
                "tr,en-US;q=0.9,en;q=0.8,ru;q=0.7,de;q=0.6,"
                "zh-CN;q=0.5,zh;q=0.4,it;q=0.3,ko;q=0.2,es;q=0.1,pl;q=0.1"
            ),
            "cache-control": "no-cache",
            "content-security-policy": "frame-ancestors 'self' https://*.playerauctions.com",
            "frame-ancestors": "self",
            "origin": "https://member.playerauctions.com",
            "pragma": "no-cache",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "strict-transport-security": "max-age=31536000; includeSubDomains",
            "user-agent": self.default_user_agent,
            "x-content-type-options": "nosniff",
            "x-xss-protection": "1; mode=block",
        }

    model_config = {"frozen": True}
