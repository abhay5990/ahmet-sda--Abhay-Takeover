"""
GameBoost-specific exceptions.

Extend the SDK's base exceptions with GameBoost-specific context.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.exceptions import AuthenticationError, ProviderError


class GameBoostError(ProviderError):
    """Base exception for GameBoost API errors."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, provider="gameboost", **kwargs)


class GameBoostAuthError(AuthenticationError):
    """GameBoost authentication failure."""

    def __init__(
        self,
        message: str = "GameBoost authentication failed",
        *,
        is_token_expired: bool = False,
    ) -> None:
        super().__init__(
            message,
            provider="gameboost",
            is_token_expired=is_token_expired,
        )
