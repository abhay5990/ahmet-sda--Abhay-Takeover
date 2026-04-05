"""
Retry decision model.

Separates error classification from retry action selection.
A RetryDecision carries what action to take and any context
needed for execution (e.g., delay hints, reason for logging).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apis_sdk.core.enums import ErrorCategory, RetryAction


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """
    The outcome of a retry strategy evaluating an error.

    Attributes:
        action: What runtime preparation to perform before retrying.
        reason: Human-readable explanation for logging/debugging.
        delay_hint: Optional delay override (e.g., from Retry-After header).
                    The retry policy may use this instead of its own backoff.
        error_category: The category of error that triggered this decision.
    """

    action: RetryAction
    reason: str = ""
    delay_hint: float | None = None
    error_category: ErrorCategory | None = None

    @property
    def should_retry(self) -> bool:
        return self.action != RetryAction.NO_RETRY

    @property
    def needs_new_session(self) -> bool:
        return self.action in (
            RetryAction.RETRY_NEW_SESSION,
            RetryAction.RETRY_NEW_PROXY_AND_SESSION,
        )

    @property
    def needs_new_proxy(self) -> bool:
        return self.action == RetryAction.RETRY_NEW_PROXY_AND_SESSION

    @property
    def needs_auth_refresh(self) -> bool:
        return self.action == RetryAction.REFRESH_AUTH_AND_RETRY

    # Convenience factories

    @staticmethod
    def no_retry(reason: str = "", *, error_category: ErrorCategory | None = None) -> RetryDecision:
        return RetryDecision(
            action=RetryAction.NO_RETRY,
            reason=reason,
            error_category=error_category,
        )

    @staticmethod
    def same(reason: str = "", *, delay_hint: float | None = None, error_category: ErrorCategory | None = None) -> RetryDecision:
        return RetryDecision(
            action=RetryAction.RETRY_SAME,
            reason=reason,
            delay_hint=delay_hint,
            error_category=error_category,
        )

    @staticmethod
    def new_session(reason: str = "", *, delay_hint: float | None = None, error_category: ErrorCategory | None = None) -> RetryDecision:
        return RetryDecision(
            action=RetryAction.RETRY_NEW_SESSION,
            reason=reason,
            delay_hint=delay_hint,
            error_category=error_category,
        )

    @staticmethod
    def new_proxy_and_session(reason: str = "", *, delay_hint: float | None = None, error_category: ErrorCategory | None = None) -> RetryDecision:
        return RetryDecision(
            action=RetryAction.RETRY_NEW_PROXY_AND_SESSION,
            reason=reason,
            delay_hint=delay_hint,
            error_category=error_category,
        )

    @staticmethod
    def refresh_auth(reason: str = "", *, error_category: ErrorCategory | None = None) -> RetryDecision:
        return RetryDecision(
            action=RetryAction.REFRESH_AUTH_AND_RETRY,
            reason=reason,
            error_category=error_category,
        )
