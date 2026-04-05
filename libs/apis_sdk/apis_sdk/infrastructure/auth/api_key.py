"""
Static API-key authentication provider.

Used by providers that authenticate with a static API key in a
custom header (e.g. ``api-key: <key>``).  Static keys do not expire
or refresh, so the lifecycle management inherited from BaseAuthProvider
is effectively a no-op.
"""

from __future__ import annotations

from apis_sdk.infrastructure.auth.base import BaseAuthProvider


class ApiKeyAuth(BaseAuthProvider):
    """
    API-key auth provider.

    Injects a static key into a named header.  No expiry, no refresh.
    """

    def __init__(
        self,
        api_key: str = "",
        *,
        header_name: str = "api-key",
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._header_name = header_name

        # Static keys never expire.
        if api_key:
            self._expires_at = float("inf")

    @property
    def api_key(self) -> str:
        return self._api_key

    def set_api_key(self, api_key: str) -> None:
        """Update the API key (e.g. after external config reload)."""
        self._api_key = api_key
        if api_key:
            self._expires_at = float("inf")

    def _do_refresh(self) -> bool:
        if self._api_key:
            self._expires_at = float("inf")
            return True
        return False

    def _build_headers(self) -> dict[str, str]:
        return {self._header_name: self._api_key}
