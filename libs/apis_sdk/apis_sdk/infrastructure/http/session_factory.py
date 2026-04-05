"""
Session factory for HTTP transports.

Centralizes requests.Session construction so transport implementations
can share one setup path for pooling, retries, and SSL behavior.
"""

from __future__ import annotations

import requests
import requests.adapters


class SessionFactory:
    """Factory methods for creating configured requests sessions."""

    @staticmethod
    def create_requests_session(
        *,
        verify_ssl: bool = True,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
        max_retries_transport: int = 0,
    ) -> requests.Session:
        """
        Create a requests.Session configured for SDK transports.

        Args:
            verify_ssl: Whether TLS certificates should be verified.
            pool_connections: Number of urllib3 connection pools.
            pool_maxsize: Max connections per pool.
            max_retries_transport: urllib3-level retry count.
        """
        session = requests.Session()
        session.verify = verify_ssl

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=max_retries_transport,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session
