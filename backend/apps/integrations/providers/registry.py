from __future__ import annotations

import os
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


# Store slugs (IntegrationAccount.slug) whose marketplace calls must go through
# the proxy pool. Comma separated; "*" restores the old proxy-for-everything
# behaviour. Default: only GameBoost GamerInstanty (GI).
PROXY_STORE_SLUGS_ENV = "SDA_PROXY_STORE_SLUGS"
DEFAULT_PROXY_STORE_SLUGS = "gameboost-gamerinstanty"


def proxy_store_slugs(env: dict | None = None) -> set[str]:
    source = os.environ if env is None else env
    raw = source.get(PROXY_STORE_SLUGS_ENV, DEFAULT_PROXY_STORE_SLUGS)
    return {part.strip().lower() for part in str(raw).split(",") if part.strip()}


def store_uses_proxy(credential: Any, env: dict | None = None) -> bool:
    """True only for stores listed in SDA_PROXY_STORE_SLUGS (or when it is "*")."""
    slugs = proxy_store_slugs(env)
    if "*" in slugs:
        return True
    account = getattr(credential, "account", None)
    slug = str(getattr(account, "slug", "") or "").strip().lower()
    return bool(slug) and slug in slugs


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
    if not store_uses_proxy(credential):
        # Only stores that really need IP isolation go through proxies.
        # Everything else connects directly (MCT lists on the same Eldorado
        # stores directly every day). Nov 2026: all 18 saved proxies died and
        # took Eldorado + GameBoost Mart down with them although only
        # GameBoost GI needs a proxy.
        proxy_pool = None
        proxy_group = None
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
