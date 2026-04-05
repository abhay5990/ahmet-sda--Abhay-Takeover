"""
Retry strategies — decide *how* to retry based on error context.

A RetryStrategy evaluates an error and returns a RetryDecision describing
what runtime action to take before retrying (same session, new session,
new proxy, auth refresh, or no retry).

This is separate from RetryPolicy, which handles *timing* (backoff, delay).
The strategy answers "what to do", the policy answers "when to do it".

Family-level strategies (MarketplaceRetryStrategy, ScrapingRetryStrategy)
provide sensible defaults. Provider-specific subclasses can override
individual decisions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from apis_sdk.core.enums import ErrorCategory, RetryAction
from apis_sdk.core.exceptions import (
    AuthenticationError,
    RateLimitError,
    SdkError,
    TimeoutError,
    TransportError,
)
from apis_sdk.infrastructure.retry.decision import RetryDecision


class RetryStrategy(ABC):
    """
    Base class for retry decision strategies.

    Subclasses implement decide() to map errors to retry actions.
    The on_before_retry() hook is called by the retry execution loop
    to perform runtime preparation (session reset, proxy rotation, etc.).
    """

    @abstractmethod
    def decide(self, attempt: int, error: Exception) -> RetryDecision:
        """
        Evaluate an error and return a retry decision.

        Args:
            attempt: Current attempt number (1-based).
            error: The exception that triggered retry evaluation.

        Returns:
            A RetryDecision describing what action to take.
        """
        ...

    def on_before_retry(self, attempt: int, decision: RetryDecision) -> None:
        """
        Hook called before each retry attempt.

        Override to perform runtime actions like session reset or
        proxy rotation. Default does nothing.

        Args:
            attempt: The attempt number about to execute (2, 3, ...).
            decision: The retry decision that was made.
        """


class DefaultRetryStrategy(RetryStrategy):
    """
    Minimal retry strategy — retry same way on transient errors.

    Suitable for simple API clients that don't need session or
    proxy manipulation.
    """

    def decide(self, attempt: int, error: Exception) -> RetryDecision:
        if isinstance(error, RateLimitError):
            return RetryDecision.same(
                "Rate limited, retry with backoff",
                delay_hint=error.retry_after,
                error_category=ErrorCategory.RATE_LIMIT,
            )

        if isinstance(error, TimeoutError):
            return RetryDecision.same(
                "Request timed out",
                error_category=ErrorCategory.TIMEOUT,
            )

        if isinstance(error, TransportError):
            return RetryDecision.same(
                "Transport error, retry same session",
                error_category=ErrorCategory.NETWORK,
            )

        if isinstance(error, SdkError) and getattr(error, "is_retryable", False):
            return RetryDecision.same(
                "Retryable provider error",
                error_category=ErrorCategory.SERVER_ERROR,
            )

        return RetryDecision.no_retry(
            f"Non-retryable: {type(error).__name__}",
        )


class MarketplaceRetryStrategy(RetryStrategy):
    """
    Retry strategy for marketplace providers.

    Conservative approach:
    - Transport/timeout errors: retry same session
    - Rate limit: retry same session (provider override can escalate)
    - Auth errors: refresh auth once on first attempt
    - Validation/not-found: never retry
    """

    def __init__(self, *, retry_on_auth: bool = True) -> None:
        self._retry_on_auth = retry_on_auth

    def decide(self, attempt: int, error: Exception) -> RetryDecision:
        if isinstance(error, RateLimitError):
            return RetryDecision.same(
                "Rate limited, retry with backoff",
                delay_hint=error.retry_after,
                error_category=ErrorCategory.RATE_LIMIT,
            )

        if isinstance(error, TimeoutError):
            return RetryDecision.same(
                "Request timed out",
                error_category=ErrorCategory.TIMEOUT,
            )

        if isinstance(error, TransportError):
            return RetryDecision.same(
                "Transport error",
                error_category=ErrorCategory.NETWORK,
            )

        if isinstance(error, AuthenticationError):
            if self._retry_on_auth and attempt == 1:
                return RetryDecision.refresh_auth(
                    "Auth failed, refresh and retry once",
                    error_category=ErrorCategory.AUTHENTICATION,
                )
            return RetryDecision.no_retry(
                "Auth failed, already retried or auth retry disabled",
                error_category=ErrorCategory.AUTHENTICATION,
            )

        if isinstance(error, SdkError) and getattr(error, "is_retryable", False):
            return RetryDecision.same(
                "Retryable provider error",
                error_category=ErrorCategory.SERVER_ERROR,
            )

        return RetryDecision.no_retry(
            f"Non-retryable: {type(error).__name__}",
        )


class ScrapingRetryStrategy(RetryStrategy):
    """
    Retry strategy for scraping/crawling clients.

    Aggressive approach:
    - Rate limit: new proxy + new session (identity rotation)
    - Transport errors: new session (connection may be poisoned)
    - Timeout: retry same (may be server-side slowness)
    """

    def decide(self, attempt: int, error: Exception) -> RetryDecision:
        if isinstance(error, RateLimitError):
            return RetryDecision.new_proxy_and_session(
                "Rate limited, rotate identity",
                delay_hint=error.retry_after,
                error_category=ErrorCategory.RATE_LIMIT,
            )

        if isinstance(error, TimeoutError):
            return RetryDecision.same(
                "Request timed out",
                error_category=ErrorCategory.TIMEOUT,
            )

        if isinstance(error, TransportError):
            return RetryDecision.new_session(
                "Transport error, reset session",
                error_category=ErrorCategory.NETWORK,
            )

        if isinstance(error, SdkError) and getattr(error, "is_retryable", False):
            return RetryDecision.new_session(
                "Retryable provider error, reset session",
                error_category=ErrorCategory.SERVER_ERROR,
            )

        return RetryDecision.no_retry(
            f"Non-retryable: {type(error).__name__}",
        )
