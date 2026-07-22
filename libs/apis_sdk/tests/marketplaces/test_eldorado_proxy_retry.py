"""Regression coverage for resilient Eldorado proxy retries."""

from __future__ import annotations

from apis_sdk.clients.marketplaces.eldorado.client import EldoradoClient
from apis_sdk.clients.marketplaces.eldorado.config import EldoradoConfig
from apis_sdk.clients.marketplaces.eldorado.retry import EldoradoRetryStrategy
from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError


class _ProxyFailingTransport:
    """Transport double that preserves the proxy-shaped failure from requests."""

    def request(self, *args, **kwargs):
        raise TransportError(
            "Proxy error for https://www.eldorado.gg/test: connection refused",
            details={"proxy_url": kwargs["proxy_url"]},
        )


def test_proxy_transport_error_requests_new_proxy_and_session():
    strategy = EldoradoRetryStrategy()

    decision = strategy.decide(
        1,
        TransportError(
            "Proxy error: connection refused",
            details={"proxy_url": "http://127.0.0.1:8080"},
        ),
    )

    assert decision.should_retry is True
    assert decision.needs_new_proxy is True
    assert decision.needs_new_session is True
    assert decision.error_category == ErrorCategory.NETWORK


def test_non_proxy_transport_error_does_not_unnecessarily_rotate_identity():
    strategy = EldoradoRetryStrategy()

    decision = strategy.decide(1, TransportError("Connection reset by peer"))

    assert decision.should_retry is True
    assert decision.needs_new_proxy is False
    assert decision.needs_new_session is False


def test_client_preserves_proxy_metadata_for_facade_retry_classification():
    client = EldoradoClient(EldoradoConfig(), _ProxyFailingTransport())
    proxy_url = "http://127.0.0.1:8080"

    result = client._request(
        HttpMethod.GET,
        "/test",
        auth_headers={},
        proxy_url=proxy_url,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.NETWORK
    assert result.error.is_retryable is True
    assert result.error.details == {"proxy_url": proxy_url}
