"""
Sync service registry — single source of truth for (resource_type, provider) → service class.

All management commands resolve service classes through this registry
instead of maintaining their own mappings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.sync.enums import ResourceType

if TYPE_CHECKING:
    from apps.sync.services.base import BaseSyncService


def _build_registry() -> dict[tuple[str, str], type[BaseSyncService]]:
    """Lazy import to avoid circular dependencies."""
    from apps.sync.services.eldorado.orders.service import EldoradoOrderSyncService
    from apps.sync.services.eldorado.orders.historical_service import EldoradoHistoricalOrderSyncService
    from apps.sync.services.eldorado.offers.service import EldoradoOfferSyncService
    from apps.sync.services.gameboost.offers.service import GameboostOfferSyncService
    from apps.sync.services.gameboost.orders.service import GameboostOrderSyncService
    from apps.sync.services.gameboost.orders.item_service import GameboostItemOrderSyncService
    from apps.sync.services.lzt.service import LztOwnedProductSyncService
    from apps.sync.services.playerauctions.orders.service import (
        PlayerAuctionsOrderSyncService,
    )
    from apps.sync.services.playerauctions.offers.service import (
        PlayerAuctionsOfferSyncService,
    )

    return {
        (ResourceType.ORDERS, 'eldorado'): EldoradoOrderSyncService,
        (ResourceType.HISTORICAL_ORDERS, 'eldorado'): EldoradoHistoricalOrderSyncService,
        (ResourceType.LISTINGS, 'eldorado'): EldoradoOfferSyncService,
        (ResourceType.ORDERS, 'gameboost'): GameboostOrderSyncService,
        (ResourceType.ITEM_ORDERS, 'gameboost'): GameboostItemOrderSyncService,
        (ResourceType.LISTINGS, 'gameboost'): GameboostOfferSyncService,
        (ResourceType.ORDERS, 'playerauctions'): PlayerAuctionsOrderSyncService,
        (ResourceType.LISTINGS, 'playerauctions'): PlayerAuctionsOfferSyncService,
        (ResourceType.OWNED_PRODUCTS, 'lzt'): LztOwnedProductSyncService,
    }


_registry: dict[tuple[str, str], type[BaseSyncService]] | None = None


def _get_registry() -> dict[tuple[str, str], type[BaseSyncService]]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_service_class(
    resource_type: str,
    provider_name: str,
) -> type[BaseSyncService] | None:
    """Return service class for given (resource_type, provider) or None."""
    return _get_registry().get((resource_type, provider_name))


def build_service(
    resource_type: str,
    provider_name: str,
    credential: Any | None = None,
    *,
    proxy_pool: Any | None = None,
    proxy_group: str | None = None,
) -> BaseSyncService:
    """Instantiate a sync service.

    If credential is provided, builds provider + client and passes them.
    If credential is None, instantiates without client (parse-only mode).
    proxy_pool/proxy_group are forwarded to get_or_build_client for proxy support.
    """
    service_class = get_service_class(resource_type, provider_name)
    if service_class is None:
        raise LookupError(
            f'No sync service registered for ({resource_type}, {provider_name}). '
            f'Registered: {sorted(_get_registry().keys())}'
        )

    if credential is not None:
        provider = get_provider(provider_name)
        client = get_or_build_client(
            provider_name, credential,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
        )
        return service_class(provider, client)

    return service_class()


def get_supported_providers() -> list[str]:
    """Return sorted list of all registered provider names."""
    return sorted({provider for _, provider in _get_registry().keys()})


def get_providers_for_resource(resource_type: str) -> list[str]:
    """Return provider names registered for a given resource type."""
    return sorted(
        provider
        for rt, provider in _get_registry().keys()
        if rt == resource_type
    )
