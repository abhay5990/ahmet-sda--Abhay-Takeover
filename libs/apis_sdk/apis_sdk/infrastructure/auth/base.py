"""
Base auth provider with common token lifecycle management.

Concrete providers (Bearer, Cognito, OAuth2) extend this base
to implement provider-specific refresh logic.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod


class BaseAuthProvider(ABC):
    """
    Base class for auth providers with thread-safe token management.

    Handles token expiry tracking and thread-safe refresh coordination
    (only one thread refreshes at a time, others wait).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires_at: float = 0.0
        self._last_refresh_error: str | None = None

    @property
    def last_refresh_error(self) -> str | None:
        """Last refresh failure reason, or ``None`` if refresh succeeded."""
        return self._last_refresh_error

    @property
    def is_expired(self) -> bool:
        """Whether the current token has expired (with a 30s buffer)."""
        return time.monotonic() >= (self._expires_at - 30.0)

    def get_auth_headers(self) -> dict[str, str]:
        """
        Return authentication headers, refreshing if needed.

        Thread-safe: concurrent callers will wait for a single refresh.
        """
        if self.is_expired:
            with self._lock:
                # Double-check after acquiring lock
                if self.is_expired:
                    self._do_refresh()
        return self._build_headers()

    def refresh(self) -> bool:
        """Force a token refresh."""
        with self._lock:
            return self._do_refresh()

    @abstractmethod
    def _do_refresh(self) -> bool:
        """
        Perform the actual token refresh.

        Implementations should update self._expires_at on success.

        Returns:
            True if refresh succeeded.
        """
        ...

    @abstractmethod
    def _build_headers(self) -> dict[str, str]:
        """Build the auth headers using the current token state."""
        ...
