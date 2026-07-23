"""PA Relay client configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaRelayConfig(BaseModel):
    """Configuration for the PA Relay service."""

    base_url: str = Field(
        default="http://35.231.166.148:3001",
        description="PA Relay base URL.",
    )
    relay_secret: str = Field(
        default="pa-relay-secret-2026",
        description="X-Relay-Secret header value for relay authentication.",
    )
    management_base_url: str = Field(
        default="http://35.196.132.30:3001",
        description="Authenticated standalone relay used only for PlayerAuctions offer-management writes.",
    )
    token_timeout: float = Field(
        default=220.0,
        gt=0,
        description="Timeout for /pa-access-token (covers full browser login ~210s).",
    )
    post_timeout: float = Field(
        default=60.0,
        gt=0,
        description="Timeout for /pa-post-offer.",
    )

    model_config = {"frozen": True}
