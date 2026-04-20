"""Shared posting utilities — used by both stock and dropship flows.

Re-exports the most commonly used helpers for convenience:

    from apps.posting.services.shared import (
        PricingDefaults, STOCK_PRICING_BASELINE, build_pricing_rule,
        extract_listing_id, persist_success,
    )

Finer-grained modules (pricing, utils, subplatform, lzt_fetcher, listing_writer)
can also be imported directly.
"""

from apps.posting.services.shared.pricing import (
    PricingDefaults,
    STOCK_PRICING_BASELINE,
    build_pricing_rule,
)
from apps.posting.services.shared.utils import (
    extract_currency_from_payload,
    extract_listing_id,
    extract_price_from_response,
    extract_title_from_payload,
    extract_title_from_response,
    serialize_response,
)
from apps.posting.services.shared.listing_writer import persist_success

__all__ = [
    'PricingDefaults',
    'STOCK_PRICING_BASELINE',
    'build_pricing_rule',
    'extract_currency_from_payload',
    'extract_listing_id',
    'extract_price_from_response',
    'extract_title_from_payload',
    'extract_title_from_response',
    'persist_success',
    'serialize_response',
]
