"""
Retry policies for SDK operations.

Policies decide whether an operation should be retried and how long
to wait between attempts. They are injected into client base classes
and can be customized per provider.

Policies handle *timing* (backoff, delay). For *action* decisions
(new session, new proxy, auth refresh), see RetryStrategy.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Callable, TypeVar

from apis_sdk.core.exceptions import (
    AuthenticationError,
    RateLimitError,
    SdkError,
    TimeoutError,
    TransportError,
)
from apis_sdk.infrastructure.retry.decision import RetryDecision

T = TypeVar("T")


class RetryPolicy(ABC):
    """Abstract retry policy."""

    @abstractmethod
    def should_retry(self, attempt: int, error: Exception) -> bool:
        """Whether to retry after this error on this attempt number."""
        ...

    @abstractmethod
    def get_delay(self, attempt: int, error: Exception) -> float:
        """Seconds to wait before the next attempt."""
        ...

    def get_delay_for_decision(self, attempt: int, error: Exception, decision: RetryDecision) -> float:
        """
        Compute delay, respecting the decision's delay_hint if present.

        Override for custom delay logic. Default: use delay_hint if set,
        otherwise fall back to get_delay().
        """
        if decision.delay_hint is not None and decision.delay_hint > 0:
            return decision.delay_hint
        return self.get_delay(attempt, error)

    def execute(
        self,
        operation: Callable[[], T],
        *,
        max_attempts: int = 3,
        strategy: object | None = None,
    ) -> T:
        """
        Execute an operation with retries according to this policy.

        Args:
            operation: Zero-argument callable to attempt.
            max_attempts: Maximum total attempts (including first).
            strategy: Optional RetryStrategy. When provided, the strategy's
                      decide() is consulted for retry decisions and
                      on_before_retry() is called before each retry attempt.
                      When not provided, falls back to should_retry().

        Returns:
            The operation result on success.

        Raises:
            The last exception if all attempts are exhausted.
        """
        # Import here to avoid circular import (strategy imports decision,
        # decision imports enums, policy imports exceptions)
        from apis_sdk.infrastructure.retry.strategy import RetryStrategy

        typed_strategy: RetryStrategy | None = None
        if isinstance(strategy, RetryStrategy):
            typed_strategy = strategy

        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise

                # Strategy-based path
                if typed_strategy is not None:
                    decision = typed_strategy.decide(attempt, exc)
                    if not decision.should_retry:
                        raise
                    typed_strategy.on_before_retry(attempt + 1, decision)
                    delay = self.get_delay_for_decision(attempt, exc, decision)
                else:
                    # Legacy path — no strategy, use should_retry()
                    if not self.should_retry(attempt, exc):
                        raise
                    delay = self.get_delay(attempt, exc)

                if delay > 0:
                    time.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("RetryPolicy exhausted without result or error.")


class ExponentialBackoff(RetryPolicy):
    """
    Exponential backoff with jitter.

    Retries on transport errors, timeouts, and rate limits.
    Does NOT retry on validation or authentication errors.
    """

    def __init__(
        self,
        *,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
    ) -> None:
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter

    def should_retry(self, attempt: int, error: Exception) -> bool:
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, (TransportError, TimeoutError)):
            return True
        if isinstance(error, SdkError) and hasattr(error, "is_retryable"):
            return getattr(error, "is_retryable", False)
        return False

    def get_delay(self, attempt: int, error: Exception) -> float:
        # Respect Retry-After header for rate limits
        if isinstance(error, RateLimitError) and error.retry_after:
            return error.retry_after

        delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
        if self._jitter:
            delay *= 0.5 + random.random() * 0.5
        return delay


class MarketplaceRetryPolicy(RetryPolicy):
    """
    Retry policy tuned for marketplace API interactions.

    Extends exponential backoff with:
    - Auth-aware retry: retries once on AuthenticationError (to allow token refresh)
    - ProviderError retry for retryable server errors
    - Rate limit retry with Retry-After respect
    """

    def __init__(
        self,
        *,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
        retry_on_auth: bool = True,
    ) -> None:
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter
        self._retry_on_auth = retry_on_auth

    def should_retry(self, attempt: int, error: Exception) -> bool:
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, (TransportError, TimeoutError)):
            return True
        # Retry auth errors once (attempt 1 only) to allow token refresh
        if self._retry_on_auth and isinstance(error, AuthenticationError) and attempt == 1:
            return True
        if isinstance(error, SdkError) and hasattr(error, "is_retryable"):
            return getattr(error, "is_retryable", False)
        return False

    def get_delay(self, attempt: int, error: Exception) -> float:
        if isinstance(error, RateLimitError) and error.retry_after:
            return error.retry_after
        # No delay for auth retry — just refresh and go
        if isinstance(error, AuthenticationError):
            return 0.0
        delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
        if self._jitter:
            delay *= 0.5 + random.random() * 0.5
        return delay


class NoRetry(RetryPolicy):
    """Never retry — used for idempotency-sensitive operations."""

    def should_retry(self, attempt: int, error: Exception) -> bool:
        return False

    def get_delay(self, attempt: int, error: Exception) -> float:
        return 0.0
