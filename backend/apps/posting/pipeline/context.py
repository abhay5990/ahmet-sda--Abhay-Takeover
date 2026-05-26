"""BuildContext factory — converts Django model fields to lib pricing + marketplace config."""

from __future__ import annotations

import logging
from typing import Any

from payload_pipeline.core.contracts import BuildContext, ListingKind
from payload_pipeline.marketplaces.eldorado import EldoradoConfig
from payload_pipeline.marketplaces.g2g import G2GConfig
from payload_pipeline.pricing.rules import PricingRule

logger = logging.getLogger(__name__)


def build_context(
    *,
    marketplace: str,
    pricing_defaults,
    store,
    kind: ListingKind,
    variant_slug: str = '',
    variant_context: dict | None = None,
) -> BuildContext:
    """Build a lib BuildContext from Django-layer inputs.

    Converts DecimalField pricing values to float (lib uses float-based PricingRule).
    Attaches the correct marketplace-specific config object per provider.

    Args:
        marketplace:      Provider slug ('eldorado', 'g2g', 'gameboost', ...).
        pricing_defaults: PricingDefaults dataclass (stock) or DropshipTargetURL
                          (dropship). Duck-typed pricing fields.
        store:            IntegrationAccount (used for G2G seller_id lookup).
        kind:             STOCK or DROPSHIPPING.
        variant_slug:     Pre-selected variant slug (empty string = none / auto).
        variant_context:  DB-driven variant mappings (from build_variant_context).
    """
    forced = pricing_defaults.forced_ending
    rule = PricingRule(
        multiplier_low=float(pricing_defaults.multiplier_low),
        multiplier_mid=float(pricing_defaults.multiplier_mid),
        multiplier_high=float(pricing_defaults.multiplier_high),
        min_price=float(pricing_defaults.min_price),
        forced_ending=float(forced) if forced is not None else None,
    )
    exchange_rate = getattr(pricing_defaults, 'exchange_rate', None)
    selected_variants: dict[str, str] | None = None
    if variant_slug and variant_slug.lower() != 'auto':
        selected_variants = {"platform": variant_slug}

    return BuildContext(
        kind=kind,
        marketplace=marketplace,
        pricing_rules={marketplace: rule},
        marketplace_config=_marketplace_config(marketplace, store, variant_slug),
        exchange_rate=float(exchange_rate) if exchange_rate is not None else None,
        variant_context=variant_context,
        selected_variants=selected_variants,
    )


def _marketplace_config(marketplace: str, store, variant_slug: str) -> Any:
    """Return the marketplace-specific config object, or None if not needed."""
    if marketplace == 'eldorado':
        return EldoradoConfig(
            image_uploader=_build_eldorado_uploader(store),
        )
    if marketplace == 'g2g':
        seller_id = store.credential.credentials.get('seller_id', '')
        return G2GConfig(seller_id=seller_id)
    return None


def _build_eldorado_uploader(store):
    """Build an EldoradoMarketplaceUploader from the store's credential.

    Returns None if the facade cannot be built (uploader will fall back to
    EldoradoImageUploader's own error handling).
    """
    try:
        from apps.integrations.providers import registry
        from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
        from .media import EldoradoMarketplaceUploader

        proxy_pool = build_proxy_pool()
        facade = registry.get_or_build_client('eldorado', store.credential, proxy_pool=proxy_pool)
        proxy_group = get_group_name(store)
        return EldoradoMarketplaceUploader(facade, proxy_group=proxy_group)
    except Exception as exc:
        logger.warning("Could not build Eldorado image uploader: %s", exc)
        return None
