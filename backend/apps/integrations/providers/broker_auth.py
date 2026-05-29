"""
Broker-backed auth provider for Eldorado.

Delegates token management to TokenBrokerService (DB-centric cache).
All facade instances sharing the same store read the same DB token —
only one Cognito refresh ever happens, coordinated by SELECT FOR UPDATE.

Local in-memory cache (via BaseAuthProvider._expires_at) avoids hitting
the DB on every API call within a sync batch.
"""

from __future__ import annotations

import time

from apis_sdk.infrastructure.auth.base import BaseAuthProvider


class BrokerAuthProvider(BaseAuthProvider):
    """Auth provider that reads tokens from the central token broker.

    Instead of calling Cognito directly, delegates to
    ``TokenBrokerService.get_token()`` which manages DB-level caching
    and concurrent refresh protection.
    """

    def __init__(self, marketplace: str, store_slug: str) -> None:
        super().__init__()
        self._marketplace = marketplace
        self._store_slug = store_slug
        self._id_token: str = ""

    def _do_refresh(self) -> bool:
        from apps.integrations.services.token_broker import TokenBrokerService

        service = TokenBrokerService()
        result = service.get_token(self._marketplace, self._store_slug)
        self._id_token = result['token']
        self._expires_at = time.monotonic() + max(60.0, result['expires_in'])
        return True

    def _build_headers(self) -> dict[str, str]:
        if not self._id_token:
            return {}
        return {"Cookie": f"__Host-EldoradoIdToken={self._id_token}"}
