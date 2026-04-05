"""
G2G-specific exceptions.

Extend the SDK's base exceptions with G2G-specific context.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.exceptions import AuthenticationError, ProviderError


class G2GError(ProviderError):
    """Base exception for G2G API errors."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, provider="g2g", **kwargs)


class G2GAuthError(AuthenticationError):
    """G2G authentication failure."""

    def __init__(
        self,
        message: str = "G2G authentication failed",
        *,
        is_token_expired: bool = False,
    ) -> None:
        super().__init__(
            message,
            provider="g2g",
            is_token_expired=is_token_expired,
        )
