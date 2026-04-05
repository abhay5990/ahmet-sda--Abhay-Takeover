from __future__ import annotations

from typing import Any

from core.exceptions import AdapterNotFoundError
from .base import AbstractProvider


_providers: dict[str, type[AbstractProvider]] = {}

# Client cache — keyed by credential PK
# Safe to cache: clients are stateless HTTP facades, Eldorado SDK auto-refreshes tokens
_client_cache: dict[int, Any] = {}


def register_provider(provider_class: type[AbstractProvider]):
    """Register a provider class (e.g., 'eldorado', 'g2g')."""
    _providers[provider_class.provider_name] = provider_class
    return provider_class


def get_provider(provider_name: str) -> AbstractProvider:
    """Get a provider instance by name."""
    provider_class = _providers.get(provider_name)
    if provider_class is None:
        raise AdapterNotFoundError(provider_name)
    return provider_class()


def get_or_build_client(
    provider_name: str,
    credential: Any,
    *,
    proxy_pool: Any | None = None,
    proxy_group: str | None = None,
) -> Any:
    """Return cached client or build a new one.

    Cache key is credential.pk — same credential always returns same client.
    proxy_pool/proxy_group are only used when building a new client.
    Cache is cleared at sync chain start so fresh clients get the current pool.
    """
    key = credential.pk
    if key not in _client_cache:
        provider = get_provider(provider_name)
        _client_cache[key] = provider.build_client(
            credential,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
        )
    return _client_cache[key]


def invalidate_client(credential_pk: int) -> None:
    """Remove a single client from cache.

    Call when credential changes (e.g. PA token refresh) or transport
    becomes invalid (e.g. proxy failure).
    """
    _client_cache.pop(credential_pk, None)


def clear_client_cache() -> None:
    """Clear all cached clients. Call at end of sync chain."""
    _client_cache.clear()


def get_registered_providers() -> dict[str, type[AbstractProvider]]:
    return dict(_providers)


def get_credential_fields(provider_name: str):
    """Get credential field definitions for a provider."""
    provider_class = _providers.get(provider_name)
    if provider_class is None:
        return []
    return provider_class.get_credential_fields()
