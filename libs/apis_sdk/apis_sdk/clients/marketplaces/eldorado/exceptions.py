"""
Eldorado-specific exceptions.

Extend the SDK's base exceptions with Eldorado-specific context.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.exceptions import AuthenticationError, ProviderError


class EldoradoError(ProviderError):
    """Base exception for Eldorado API errors."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, provider="eldorado", **kwargs)


class EldoradoAuthError(AuthenticationError):
    """Eldorado authentication failure (Cognito SRP)."""

    def __init__(
        self,
        message: str = "Eldorado authentication failed",
        *,
        is_token_expired: bool = False,
    ) -> None:
        super().__init__(
            message,
            provider="eldorado",
            is_token_expired=is_token_expired,
        )


class EldoradoAccountDeletedError(EldoradoError):
    """Raised when Eldorado reports the seller account has been deleted/banned."""

    def __init__(self, message: str = "Eldorado account has been deleted") -> None:
        super().__init__(message, is_retryable=False)


class EldoradoPasswordLockoutError(EldoradoError):
    """Raised when Eldorado locks out due to too many password attempts."""

    def __init__(self, message: str = "Password attempt limit exceeded") -> None:
        super().__init__(message, is_retryable=True)


class EldoradoProviderNotReadyError(EldoradoError):
    """Raised when Eldorado integration is intentionally not ready."""

    def __init__(self, message: str) -> None:
        super().__init__(message, is_retryable=False)
