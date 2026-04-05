"""
SDK exception hierarchy.

All SDK exceptions inherit from SdkError so callers can catch broadly
or narrowly as needed. Each exception carries structured context for
logging and error reporting.
"""

from __future__ import annotations

from typing import Any


class SdkError(Exception):
    """Base exception for all SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.details = details or {}


class TransportError(SdkError):
    """
    HTTP transport-level failure.

    Raised for connection errors, DNS failures, SSL errors, and similar
    issues that prevent a request from reaching the provider.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, details=details)
        self.status_code = status_code


class AuthenticationError(SdkError):
    """
    Authentication or authorization failure (401/403).

    Raised when credentials are invalid, expired, or insufficient.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        provider: str | None = None,
        is_token_expired: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, details=details)
        self.is_token_expired = is_token_expired


class RateLimitError(SdkError):
    """
    Rate limit exceeded (429).

    Carries retry_after hint when the provider supplies one.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        provider: str | None = None,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, details=details)
        self.retry_after = retry_after


class ValidationError(SdkError):
    """
    Request validation failure (422 or client-side validation).

    Carries structured field-level errors when available.
    """

    def __init__(
        self,
        message: str = "Validation failed",
        *,
        provider: str | None = None,
        field_errors: dict[str, list[str]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, details=details)
        self.field_errors = field_errors or {}


class ProviderError(SdkError):
    """
    Provider-side error (5xx or provider-specific business error).

    Used when the provider accepts the request but returns an error
    response indicating a server-side issue.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        is_retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, details=details)
        self.status_code = status_code
        self.is_retryable = is_retryable


class TimeoutError(TransportError):
    """
    Request timeout.

    Separate from TransportError for granular catch handling —
    callers may want to retry on timeout but not on SSL errors.
    """

    def __init__(
        self,
        message: str = "Request timed out",
        *,
        provider: str | None = None,
        timeout_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=None, details=details)
        self.timeout_seconds = timeout_seconds
