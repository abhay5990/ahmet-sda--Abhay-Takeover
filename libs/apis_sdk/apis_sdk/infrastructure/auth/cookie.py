"""
Cookie-based session authentication provider.

Used by scraping-domain providers that authenticate via HTTP cookies
(e.g., ``connect.sid``, ``session_id``).  Cookie values do not expire
within the SDK — periodic refresh / re-login decisions remain app-level.

ADR: docs/adr/0003-cookie-session-auth.md
"""

from __future__ import annotations

from apis_sdk.infrastructure.auth.base import BaseAuthProvider


class CookieAuth(BaseAuthProvider):
    """
    Cookie auth provider.

    Injects a cookie into the ``Cookie`` header.  No automatic expiry
    or refresh — the app layer calls ``set_cookie()`` when it obtains
    a fresh session cookie.

    Args:
        cookie_name: Cookie name (e.g., ``"connect.sid"``).
        cookie_value: Initial cookie value.  May be empty if the
            cookie will be set later via ``set_cookie()``.
    """

    def __init__(
        self,
        cookie_name: str,
        cookie_value: str = "",
    ) -> None:
        super().__init__()
        self._cookie_name = cookie_name
        self._cookie_value = cookie_value

        # Cookies managed externally — never expire within the SDK.
        if cookie_value:
            self._expires_at = float("inf")

    @property
    def cookie_name(self) -> str:
        return self._cookie_name

    @property
    def cookie_value(self) -> str:
        return self._cookie_value

    def set_cookie(self, value: str) -> None:
        """Update the cookie value (e.g., after app-level re-login)."""
        self._cookie_value = value
        if value:
            self._expires_at = float("inf")

    def _do_refresh(self) -> bool:
        if self._cookie_value:
            self._expires_at = float("inf")
            return True
        return False

    def _build_headers(self) -> dict[str, str]:
        return {"Cookie": f"{self._cookie_name}={self._cookie_value}"}
