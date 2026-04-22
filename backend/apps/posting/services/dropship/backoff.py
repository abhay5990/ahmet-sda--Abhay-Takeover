"""Shared backoff and error tracking — used by poster and cleaner threads.

Provides:
- ErrorTracker: per-thread error counter with exponential backoff
- PauseRequired: exception signalling thread should enter PAUSED state (permanent)
- TemporaryPauseRequired: exception signalling a timed cooldown, then auto-resume
- classify_api_error: maps ApiResult failures to error categories
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apis_sdk.core.result import ApiResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Exponential backoff for 429 rate limits
BACKOFF_BASE: float = 4.0       # Initial wait: 4s
BACKOFF_FACTOR: float = 2.0     # Multiplier: 4 -> 8 -> 16 -> 32 -> 64
BACKOFF_MAX: float = 64.0       # Cap at 64s
MAX_CONSECUTIVE_429: int = 5    # 5 consecutive 429s -> 1-hour cooldown, then resume

# Validation error sliding window
ERROR_WINDOW = timedelta(hours=1)
MAX_ERRORS_IN_WINDOW: int = 3   # 3 validation errors in 1hr -> permanent PAUSE

# Server error retries — temporary cooldown, not permanent disable
MAX_SERVER_RETRIES: int = 5     # 5 consecutive 5xx -> 1-hour cooldown, then resume
SERVER_COOLDOWN: float = 3600.0  # 1 hour


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PauseRequired(Exception):
    """Raised when ErrorTracker decides the thread must be permanently paused.

    Used for validation error floods — conditions that require a code fix
    before the thread should resume.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class TemporaryPauseRequired(Exception):
    """Raised when ErrorTracker decides a timed cooldown is needed.

    Used for consecutive server errors (5xx / network) — transient platform
    outages that should resolve on their own.  The caller sleeps for
    ``wait_seconds`` and resumes automatically without human intervention.
    """

    def __init__(self, reason: str, wait_seconds: float = SERVER_COOLDOWN) -> None:
        self.reason = reason
        self.wait_seconds = wait_seconds
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def classify_api_error(api_result: ApiResult) -> str:
    """Classify an ApiResult failure into an error category.

    Returns one of: 'rate_limit', 'validation', 'server', 'auth',
    'not_found', 'maintenance', 'success'.
    Falls back to 'unknown' for unrecognised errors.

    Uses ErrorCategory enum from the SDK when available, with status_code
    fallback for edge cases.
    """
    if api_result.ok:
        return 'success'

    error = api_result.error
    if error is None:
        return 'unknown'

    # LZT maintenance mode — SDK tags this in details
    details = getattr(error, 'details', {}) or {}
    if details.get('maintenance'):
        return 'maintenance'

    # Primary: use ErrorCategory enum (set by all SDK clients)
    from apis_sdk.core.enums import ErrorCategory

    category = getattr(error, 'category', None)
    if category is not None:
        _MAP = {
            ErrorCategory.RATE_LIMIT: 'rate_limit',
            ErrorCategory.VALIDATION: 'validation',
            ErrorCategory.SERVER_ERROR: 'server',
            ErrorCategory.NETWORK: 'server',
            ErrorCategory.TIMEOUT: 'server',
            ErrorCategory.AUTHENTICATION: 'auth',
            ErrorCategory.NOT_FOUND: 'not_found',
            ErrorCategory.CONFLICT: 'validation',
        }
        mapped = _MAP.get(category)
        if mapped is not None:
            return mapped

    # Fallback: raw status_code
    status = getattr(error, 'status_code', None) or api_result.status_code
    if status is not None:
        if status == 429:
            return 'rate_limit'
        if 400 <= status < 500:
            return 'validation'
        if status >= 500:
            return 'server'

    return 'unknown'


# ---------------------------------------------------------------------------
# ErrorTracker
# ---------------------------------------------------------------------------

@dataclass
class ErrorTracker:
    """Per-thread error counter with exponential backoff.

    Each poster/cleaner thread owns its own instance. Counters are in-memory
    only — no DB writes needed.

    Raises PauseRequired (permanent) for rate-limit / validation floods.
    Raises TemporaryPauseRequired (1-hour cooldown) for server error streaks.
    """

    stop_event: Event

    # 429 tracking
    _consecutive_429: int = field(default=0, init=False, repr=False)

    # 400 tracking (sliding window)
    _window_start: datetime | None = field(default=None, init=False, repr=False)
    _errors_in_window: int = field(default=0, init=False, repr=False)

    # 5xx tracking
    _consecutive_server_errors: int = field(default=0, init=False, repr=False)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def on_success(self) -> None:
        """Successful request — reset all consecutive counters."""
        self._consecutive_429 = 0
        self._consecutive_server_errors = 0

    def on_rate_limit(self, retry_after: float | None = None) -> None:
        """Handle 429 rate limit.

        1. Increments counter.
        2. If threshold reached -> raises TemporaryPauseRequired (1-hour cooldown).
        3. Otherwise, sleeps with exponential backoff (interruptible via stop_event).

        Args:
            retry_after: Optional server-suggested wait time (from Retry-After header).
        """
        self._consecutive_429 += 1
        self._consecutive_server_errors = 0

        if self._consecutive_429 >= MAX_CONSECUTIVE_429:
            raise TemporaryPauseRequired(
                f"{MAX_CONSECUTIVE_429}x consecutive rate limit (429)",
                wait_seconds=SERVER_COOLDOWN,
            )

        delay = _backoff_delay(self._consecutive_429)
        if retry_after is not None and retry_after > delay:
            delay = min(retry_after, BACKOFF_MAX)

        logger.warning(
            "Rate limited, backing off %.1fs (attempt %d/%d)",
            delay, self._consecutive_429, MAX_CONSECUTIVE_429,
        )
        self.stop_event.wait(timeout=delay)

    def on_validation_error(self, item_id: str | int = '', *, last_error: str = '') -> None:
        """Handle 400/422 validation error.

        Tracks errors in a 1-hour sliding window. If threshold is exceeded,
        raises PauseRequired (permanent). The caller is responsible for
        skipping the item and writing a PostingLog entry.
        """
        self._consecutive_429 = 0
        self._consecutive_server_errors = 0

        now = datetime.now(timezone.utc)
        if self._window_start is None or now - self._window_start > ERROR_WINDOW:
            self._window_start = now
            self._errors_in_window = 0

        self._errors_in_window += 1
        if last_error:
            self._last_validation_error = last_error

        if self._errors_in_window >= MAX_ERRORS_IN_WINDOW:
            reason = f"{MAX_ERRORS_IN_WINDOW}x validation errors in 1 hour (400)"
            detail = getattr(self, '_last_validation_error', '')
            if detail:
                reason += f" | last: {detail[:300]}"
            raise PauseRequired(reason)

    def on_server_error(self) -> None:
        """Handle 5xx / network / timeout error.

        1. Increments counter.
        2. If threshold reached -> raises TemporaryPauseRequired (1-hour cooldown).
        3. Otherwise, sleeps with exponential backoff (interruptible via stop_event).
        """
        self._consecutive_server_errors += 1
        self._consecutive_429 = 0

        if self._consecutive_server_errors >= MAX_SERVER_RETRIES:
            raise TemporaryPauseRequired(
                f"{MAX_SERVER_RETRIES}x consecutive server errors (5xx)",
                wait_seconds=SERVER_COOLDOWN,
            )

        delay = _backoff_delay(self._consecutive_server_errors)
        logger.warning(
            "Server error, backing off %.1fs (attempt %d/%d)",
            delay, self._consecutive_server_errors, MAX_SERVER_RETRIES,
        )
        self.stop_event.wait(timeout=delay)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backoff_delay(attempt: int) -> float:
    """Calculate exponential backoff delay for the given attempt number.

    attempt=1 -> 4s, attempt=2 -> 8s, attempt=3 -> 16s, ..., capped at 64s.
    """
    return min(BACKOFF_BASE * (BACKOFF_FACTOR ** (attempt - 1)), BACKOFF_MAX)
