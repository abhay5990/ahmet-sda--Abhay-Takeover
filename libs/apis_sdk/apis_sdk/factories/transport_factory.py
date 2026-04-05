"""
Transport factory.

Creates configured HTTP transport instances.
"""

from __future__ import annotations

import requests

from apis_sdk.infrastructure.http.requests_transport import RequestsTransport


class TransportFactory:
    """Factory for creating HTTP transport instances."""

    @staticmethod
    def create_requests_transport(
        *,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
        max_retries_transport: int = 0,
        session: requests.Session | None = None,
    ) -> RequestsTransport:
        """
        Create a requests-backed HTTP transport.

        Args:
            timeout: Default request timeout in seconds.
            default_headers: Headers to include in every request.
            verify_ssl: Whether to verify SSL certificates.
            pool_connections: urllib3 connection pool size.
            pool_maxsize: Max connections per pool.
            max_retries_transport: urllib3-level retry count.
            session: Optional pre-created requests session.

        Returns:
            Configured RequestsTransport instance.
        """
        headers = {
            "User-Agent": "apis-sdk/0.1.0",
            "Accept": "application/json",
        }
        if default_headers:
            headers.update(default_headers)

        return RequestsTransport(
            default_timeout=timeout,
            default_headers=headers,
            verify_ssl=verify_ssl,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries_transport=max_retries_transport,
            session=session,
        )
