"""
Simple Bearer token authentication provider.

Used by providers that authenticate with a static or refreshable
Bearer token in the Authorization header.
"""

from __future__ import annotations

import time

from apis_sdk.infrastructure.auth.base import BaseAuthProvider


class BearerTokenAuth(BaseAuthProvider):
    """
    Bearer token auth provider.

    For static tokens (no refresh needed), set token directly and
    set a far-future expiry. For refreshable tokens, subclass and
    override _do_refresh().
    """

    def __init__(
        self,
        token: str = "",
        *,
        token_ttl_seconds: float = 3600.0,
    ) -> None:
        super().__init__()
        self._token = token
        self._token_ttl = token_ttl_seconds

        if token:
            self._expires_at = time.monotonic() + token_ttl_seconds

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str, *, ttl: float | None = None) -> None:
        """Update the token and reset expiry."""
        self._token = token
        self._expires_at = time.monotonic() + (ttl or self._token_ttl)

    def _do_refresh(self) -> bool:
        """
        Default: no-op for static tokens.

        Override in subclasses that support token refresh via API calls.
        """
        if self._token:
            self._expires_at = time.monotonic() + self._token_ttl
            return True
        return False

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
