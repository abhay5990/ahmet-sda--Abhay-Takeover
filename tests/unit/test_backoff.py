"""Tests for apps.posting.services.dropship.backoff module.

Usage:
    cd backend && python -m pytest ../tests/unit/test_backoff.py -v
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from threading import Event
from unittest.mock import patch

# Add backend to path so `apps.*` imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
# Add libs to path so `apis_sdk.*` imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'apis_sdk'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

import django
django.setup()

import pytest

from apps.posting.services.dropship.backoff import (
    BACKOFF_BASE,
    BACKOFF_MAX,
    MAX_CONSECUTIVE_429,
    MAX_ERRORS_IN_WINDOW,
    MAX_SERVER_RETRIES,
    ErrorTracker,
    PauseRequired,
    _backoff_delay,
    classify_api_error,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def stop_event():
    return Event()


@pytest.fixture
def tracker(stop_event):
    return ErrorTracker(stop_event=stop_event)


@dataclass
class FakeErrorDetail:
    category: object = None
    message: str = ''
    status_code: int | None = None
    retry_after: float | None = None


@dataclass
class FakeApiResult:
    ok: bool = True
    data: object = None
    error: FakeErrorDetail | None = None
    status_code: int | None = None


# ---------------------------------------------------------------------------
# _backoff_delay
# ---------------------------------------------------------------------------

class TestBackoffDelay:
    def test_first_attempt(self):
        assert _backoff_delay(1) == 4.0

    def test_second_attempt(self):
        assert _backoff_delay(2) == 8.0

    def test_third_attempt(self):
        assert _backoff_delay(3) == 16.0

    def test_fourth_attempt(self):
        assert _backoff_delay(4) == 32.0

    def test_fifth_attempt(self):
        assert _backoff_delay(5) == 64.0

    def test_capped_at_max(self):
        assert _backoff_delay(10) == BACKOFF_MAX


# ---------------------------------------------------------------------------
# classify_api_error
# ---------------------------------------------------------------------------

class TestClassifyApiError:
    def test_success(self):
        result = FakeApiResult(ok=True)
        assert classify_api_error(result) == 'success'

    def test_no_error_detail(self):
        result = FakeApiResult(ok=False, error=None)
        assert classify_api_error(result) == 'unknown'

    def test_rate_limit_by_category(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.RATE_LIMIT)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'rate_limit'

    def test_validation_by_category(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.VALIDATION)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'validation'

    def test_server_error_by_category(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.SERVER_ERROR)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'server'

    def test_network_maps_to_server(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.NETWORK)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'server'

    def test_timeout_maps_to_server(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.TIMEOUT)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'server'

    def test_auth_by_category(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.AUTHENTICATION)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'auth'

    def test_not_found_by_category(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.NOT_FOUND)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'not_found'

    def test_conflict_maps_to_validation(self):
        from apis_sdk.core.enums import ErrorCategory
        error = FakeErrorDetail(category=ErrorCategory.CONFLICT)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'validation'

    def test_fallback_status_code_429(self):
        error = FakeErrorDetail(category=None, status_code=429)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'rate_limit'

    def test_fallback_status_code_400(self):
        error = FakeErrorDetail(category=None, status_code=400)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'validation'

    def test_fallback_status_code_500(self):
        error = FakeErrorDetail(category=None, status_code=500)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'server'

    def test_fallback_status_code_from_result(self):
        """status_code on ApiResult level (not error) is used as fallback."""
        error = FakeErrorDetail(category=None, status_code=None)
        result = FakeApiResult(ok=False, error=error, status_code=503)
        assert classify_api_error(result) == 'server'

    def test_completely_unknown(self):
        error = FakeErrorDetail(category=None, status_code=None)
        result = FakeApiResult(ok=False, error=error)
        assert classify_api_error(result) == 'unknown'


# ---------------------------------------------------------------------------
# PauseRequired
# ---------------------------------------------------------------------------

class TestPauseRequired:
    def test_has_reason(self):
        exc = PauseRequired("test reason")
        assert exc.reason == "test reason"
        assert str(exc) == "test reason"

    def test_is_exception(self):
        assert issubclass(PauseRequired, Exception)


# ---------------------------------------------------------------------------
# ErrorTracker — on_success
# ---------------------------------------------------------------------------

class TestErrorTrackerOnSuccess:
    def test_resets_429_counter(self, tracker):
        tracker._consecutive_429 = 3
        tracker.on_success()
        assert tracker._consecutive_429 == 0

    def test_resets_server_counter(self, tracker):
        tracker._consecutive_server_errors = 2
        tracker.on_success()
        assert tracker._consecutive_server_errors == 0

    def test_does_not_reset_validation_window(self, tracker):
        """Validation window is time-based, not reset by success."""
        tracker._errors_in_window = 2
        tracker.on_success()
        assert tracker._errors_in_window == 2


# ---------------------------------------------------------------------------
# ErrorTracker — on_rate_limit
# ---------------------------------------------------------------------------

class TestErrorTrackerOnRateLimit:
    def test_increments_429_counter(self, tracker, stop_event):
        stop_event.set()  # prevent actual sleep
        tracker.on_rate_limit()
        assert tracker._consecutive_429 == 1

    def test_resets_server_counter(self, tracker, stop_event):
        stop_event.set()
        tracker._consecutive_server_errors = 2
        tracker.on_rate_limit()
        assert tracker._consecutive_server_errors == 0

    def test_raises_pause_at_threshold(self, tracker):
        tracker._consecutive_429 = MAX_CONSECUTIVE_429 - 1
        with pytest.raises(PauseRequired, match="rate limit"):
            tracker.on_rate_limit()

    def test_waits_with_backoff(self, tracker, stop_event):
        """Verify stop_event.wait is called with correct delay."""
        with patch.object(stop_event, 'wait') as mock_wait:
            tracker.on_rate_limit()
        mock_wait.assert_called_once_with(timeout=BACKOFF_BASE)

    def test_escalating_backoff(self, tracker, stop_event):
        """Each call increases the backoff delay."""
        delays = []
        with patch.object(stop_event, 'wait', side_effect=lambda timeout: delays.append(timeout)):
            tracker.on_rate_limit()  # 4s
            tracker.on_rate_limit()  # 8s
            tracker.on_rate_limit()  # 16s

        assert delays == [4.0, 8.0, 16.0]

    def test_retry_after_overrides_when_larger(self, tracker, stop_event):
        with patch.object(stop_event, 'wait') as mock_wait:
            tracker.on_rate_limit(retry_after=30.0)
        mock_wait.assert_called_once_with(timeout=30.0)

    def test_retry_after_ignored_when_smaller(self, tracker, stop_event):
        with patch.object(stop_event, 'wait') as mock_wait:
            tracker.on_rate_limit(retry_after=1.0)
        # Should use calculated backoff (4s), not retry_after (1s)
        mock_wait.assert_called_once_with(timeout=BACKOFF_BASE)

    def test_retry_after_capped_at_max(self, tracker, stop_event):
        with patch.object(stop_event, 'wait') as mock_wait:
            tracker.on_rate_limit(retry_after=999.0)
        mock_wait.assert_called_once_with(timeout=BACKOFF_MAX)


# ---------------------------------------------------------------------------
# ErrorTracker — on_validation_error
# ---------------------------------------------------------------------------

class TestErrorTrackerOnValidationError:
    def test_increments_window_counter(self, tracker):
        tracker.on_validation_error('item-1')
        assert tracker._errors_in_window == 1

    def test_resets_other_counters(self, tracker):
        tracker._consecutive_429 = 3
        tracker._consecutive_server_errors = 2
        tracker.on_validation_error('item-1')
        assert tracker._consecutive_429 == 0
        assert tracker._consecutive_server_errors == 0

    def test_raises_pause_at_threshold(self, tracker):
        from datetime import datetime, timezone
        tracker._window_start = datetime.now(timezone.utc)
        tracker._errors_in_window = MAX_ERRORS_IN_WINDOW - 1
        with pytest.raises(PauseRequired, match="validation"):
            tracker.on_validation_error('item-3')

    def test_window_resets_after_expiry(self, tracker):
        """If window has expired, counter resets."""
        from datetime import datetime, timedelta, timezone
        tracker._window_start = datetime.now(timezone.utc) - timedelta(hours=2)
        tracker._errors_in_window = MAX_ERRORS_IN_WINDOW - 1
        # Should NOT raise — window expired, counter resets
        tracker.on_validation_error('item-new')
        assert tracker._errors_in_window == 1

    def test_first_call_initializes_window(self, tracker):
        assert tracker._window_start is None
        tracker.on_validation_error('item-1')
        assert tracker._window_start is not None
        assert tracker._errors_in_window == 1


# ---------------------------------------------------------------------------
# ErrorTracker — on_server_error
# ---------------------------------------------------------------------------

class TestErrorTrackerOnServerError:
    def test_increments_server_counter(self, tracker, stop_event):
        stop_event.set()
        tracker.on_server_error()
        assert tracker._consecutive_server_errors == 1

    def test_resets_429_counter(self, tracker, stop_event):
        stop_event.set()
        tracker._consecutive_429 = 3
        tracker.on_server_error()
        assert tracker._consecutive_429 == 0

    def test_raises_pause_at_threshold(self, tracker):
        tracker._consecutive_server_errors = MAX_SERVER_RETRIES - 1
        with pytest.raises(PauseRequired, match="server"):
            tracker.on_server_error()

    def test_waits_with_backoff(self, tracker, stop_event):
        with patch.object(stop_event, 'wait') as mock_wait:
            tracker.on_server_error()
        mock_wait.assert_called_once_with(timeout=BACKOFF_BASE)

    def test_escalating_backoff(self, tracker, stop_event):
        delays = []
        with patch.object(stop_event, 'wait', side_effect=lambda timeout: delays.append(timeout)):
            tracker.on_server_error()  # 4s
            tracker.on_server_error()  # 8s

        assert delays == [4.0, 8.0]


# ---------------------------------------------------------------------------
# ErrorTracker — stop_event interaction
# ---------------------------------------------------------------------------

class TestErrorTrackerStopEvent:
    def test_backoff_returns_immediately_if_stopped(self, tracker, stop_event):
        """If stop_event is already set, wait() returns immediately."""
        stop_event.set()
        start = time.monotonic()
        tracker.on_rate_limit()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # Should be near-instant

    def test_server_backoff_returns_immediately_if_stopped(self, tracker, stop_event):
        stop_event.set()
        start = time.monotonic()
        tracker.on_server_error()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0


# ---------------------------------------------------------------------------
# ErrorTracker — combined scenarios
# ---------------------------------------------------------------------------

class TestErrorTrackerCombined:
    def test_mixed_errors_reset_correctly(self, tracker, stop_event):
        stop_event.set()
        tracker.on_rate_limit()
        assert tracker._consecutive_429 == 1
        assert tracker._consecutive_server_errors == 0

        tracker.on_server_error()
        assert tracker._consecutive_429 == 0
        assert tracker._consecutive_server_errors == 1

        tracker.on_success()
        assert tracker._consecutive_429 == 0
        assert tracker._consecutive_server_errors == 0

    def test_success_between_rate_limits_resets_counter(self, tracker, stop_event):
        stop_event.set()
        for _ in range(MAX_CONSECUTIVE_429 - 1):
            tracker.on_rate_limit()
        tracker.on_success()
        # Should NOT raise — counter was reset
        tracker.on_rate_limit()
        assert tracker._consecutive_429 == 1

    def test_full_429_escalation_to_pause(self, tracker, stop_event):
        stop_event.set()
        for i in range(MAX_CONSECUTIVE_429 - 1):
            tracker.on_rate_limit()
        with pytest.raises(PauseRequired):
            tracker.on_rate_limit()
