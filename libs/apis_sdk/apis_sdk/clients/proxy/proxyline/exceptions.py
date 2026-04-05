"""
Proxyline-specific exceptions.

These extend the SDK's base exceptions with provider-specific context.
"""

from typing import Any

from apis_sdk.core.exceptions import ProviderError


class ProxylineError(ProviderError):
    """Base exception for Proxyline API errors."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, provider="proxyline", **kwargs)


class ProxylineAuthError(ProxylineError):
    """Proxyline API key is invalid or expired."""

    def __init__(self, message: str = "Invalid Proxyline API key") -> None:
        super().__init__(message, is_retryable=False)
