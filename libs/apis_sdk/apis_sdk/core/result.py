"""
Unified result wrapper for all SDK operations.

Every provider client returns ApiResult[T] so callers get a consistent
interface regardless of which provider they're talking to.

Usage:
    result = client.get_offers()
    if result.ok:
        for offer in result.data:
            ...
    else:
        print(result.error.message)
        if result.error.is_retryable:
            # schedule retry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from apis_sdk.core.enums import ErrorCategory

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """Structured error information attached to a failed ApiResult."""

    category: ErrorCategory
    message: str
    status_code: int | None = None
    provider: str | None = None
    retry_after: float | None = None
    is_retryable: bool = False
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApiResult(Generic[T]):
    """
    Unified result wrapper for SDK operations.

    Encapsulates success/failure without raising exceptions, enabling
    callers to handle errors in a functional style. Providers should
    raise exceptions only for truly exceptional conditions (e.g., bugs);
    expected failures (4xx, 5xx) are returned as failed results.

    Attributes:
        ok: Whether the operation succeeded.
        data: The typed response data (None on failure).
        error: Structured error detail (None on success).
        status_code: Raw HTTP status code from the provider.
        meta: Optional metadata (request_id, timing, pagination, etc.)
    """

    ok: bool
    data: T | None = None
    error: ErrorDetail | None = None
    status_code: int | None = None
    meta: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def success(data: T, *, status_code: int | None = None, meta: dict[str, object] | None = None) -> ApiResult[T]:
        """Create a successful result."""
        return ApiResult(ok=True, data=data, status_code=status_code, meta=meta or {})

    @staticmethod
    def failure(
        error: ErrorDetail,
        *,
        status_code: int | None = None,
        meta: dict[str, object] | None = None,
    ) -> ApiResult[T]:
        """Create a failed result."""
        code = status_code or error.status_code
        return ApiResult(ok=False, error=error, status_code=code, meta=meta or {})

    @staticmethod
    def from_error(
        category: ErrorCategory,
        message: str,
        *,
        status_code: int | None = None,
        provider: str | None = None,
        retry_after: float | None = None,
        is_retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> ApiResult[T]:
        """Convenience factory — creates a failed result from raw error fields."""
        error = ErrorDetail(
            category=category,
            message=message,
            status_code=status_code,
            provider=provider,
            retry_after=retry_after,
            is_retryable=is_retryable,
            details=details or {},
        )
        return ApiResult.failure(error, status_code=status_code)
