"""Build variant context dicts for pipeline injection.

Queries GameVariant + GameVariantMapping + GameVariantLimit from DB and
produces a plain dict that the pipeline lib can consume without any
Django dependency.

Also used by VariantRouter for capacity-aware variant selection — the
``limit``, ``stock_reserve``, and ``active`` fields drive routing decisions.
"""

from __future__ import annotations

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import GameVariant, GameVariantLimit, GameVariantMapping
from apps.posting.services.variant_routing import (
    DEFAULT_MAX_OFFERS,
    DEFAULT_MAX_OFFERS_REGION,
    DEFAULT_STOCK_RESERVE,
    DEFAULT_STOCK_RESERVE_REGION,
)
from apps.posting.services.variant_slug import variant_value_contains_slug


def build_variant_context(
    *,
    store,
    game,
    marketplace: str,
) -> dict | None:
    """Build variant context dict for a store + game + marketplace.

    Returns None if the game has no variants at all.

    Shape of returned dict::

        {
            "platform": {
                "pc": {
                    "slug": "pc",
                    "label": "PC",
                    "external_id": "0",
                    "external_name": "",
                    "limit": 300,
                    "stock_reserve": 300,
                    "active": 42,
                },
                ...
            },
        }

    Each variant type becomes a top-level key. Each option is keyed by
    source_key (if set) or slug. Only variants that have a mapping for
    the requested marketplace are included.

    ``limit`` and ``stock_reserve`` default to DEFAULT_MAX_OFFERS /
    DEFAULT_STOCK_RESERVE when no GameVariantLimit record exists.
    ``active`` is the count of LISTED listings for the store+game+variant.
    """
    variants = list(
        GameVariant.objects
        .filter(game=game)
        .order_by('type', 'sort_order')
    )
    if not variants:
        return None

    # Batch-load mappings for this marketplace
    mappings_by_variant: dict[int, GameVariantMapping] = {
        m.variant_id: m
        for m in GameVariantMapping.objects.filter(
            variant__game=game,
            marketplace=marketplace,
        )
    }

    # Batch-load limits for this store
    limits_by_variant: dict[int, GameVariantLimit] = {
        vl.variant_id: vl
        for vl in GameVariantLimit.objects.filter(
            store=store,
            variant__game=game,
        )
    }

    # Active listing counts per component slug (only LISTED status).
    # Listing.variant may be a composite value such as "eu-pc".
    listing_variant_values = list(
        Listing.objects.filter(
            integration_account=store,
            game=game,
            status=ListingStatus.LISTED,
        )
        .values_list('variant', flat=True)
    )
    active_counts: dict[str, int] = {v.slug: 0 for v in variants}
    known_slugs = {slug.lower() for slug in active_counts}
    for value in listing_variant_values:
        for variant in variants:
            if variant_value_contains_slug(
                value,
                variant.slug,
                known_slugs=known_slugs,
            ):
                active_counts[variant.slug] += 1

    result: dict[str, dict[str, dict]] = {}

    for v in variants:
        mapping = mappings_by_variant.get(v.id)
        if not mapping:
            continue

        if v.type not in result:
            result[v.type] = {}

        key = v.source_key or v.slug
        limit = limits_by_variant.get(v.id)
        is_region = v.type == 'region'
        def_limit = DEFAULT_MAX_OFFERS_REGION if is_region else DEFAULT_MAX_OFFERS
        def_reserve = DEFAULT_STOCK_RESERVE_REGION if is_region else DEFAULT_STOCK_RESERVE

        result[v.type][key] = {
            "slug": v.slug,
            "label": v.label,
            "external_id": mapping.external_id,
            "external_name": mapping.external_name or "",
            "limit": limit.max_offers if limit else def_limit,
            "stock_reserve": limit.stock_reserve if limit else def_reserve,
            "active": active_counts.get(v.slug, 0),
        }

    return result if result else None
