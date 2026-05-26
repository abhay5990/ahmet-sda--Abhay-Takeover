"""Pricing defaults + job-scoped override + library rule builder.

Used by both stock and dropship flows as a single-source pricing definition.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from payload_pipeline.pricing.rules import PricingRule as LibPricingRule


@dataclass(frozen=True)
class PricingDefaults:
    """Immutable pricing configuration.

    Common shape for stock (job.settings-derived) and dropship (DropshipTargetURL-derived)
    callsites. Used as input to ``build_pricing_rule``.
    """
    multiplier_low: float
    multiplier_mid: float
    multiplier_high: float
    min_price: float
    forced_ending: float | None = None
    exchange_rate: float | None = None

    @classmethod
    def from_model(cls, obj) -> 'PricingDefaults':
        """Build from a model instance with the matching field names.

        Used for DropshipTargetURL.
        """
        raw_rate = getattr(obj, 'exchange_rate', None)
        return cls(
            multiplier_low=float(obj.multiplier_low),
            multiplier_mid=float(obj.multiplier_mid),
            multiplier_high=float(obj.multiplier_high),
            min_price=float(obj.min_price),
            forced_ending=(
                float(obj.forced_ending)
                if obj.forced_ending is not None else None
            ),
            exchange_rate=(
                float(raw_rate)
                if raw_rate is not None else None
            ),
        )

    def with_overrides(self, overrides: Mapping[str, object]) -> 'PricingDefaults':
        """Return a new (immutable) copy with job-scoped overrides applied.

        Only recognised pricing fields with non-None values are applied.
        Non-pricing keys (variant, account_type, ...) are ignored here.
        """
        allowed = {
            'multiplier_low', 'multiplier_mid', 'multiplier_high',
            'min_price', 'forced_ending', 'exchange_rate',
        }
        patch = {
            k: (float(v) if v is not None else None)
            for k, v in overrides.items()
            if k in allowed and v is not None
        }
        return replace(self, **patch) if patch else self


# System-wide pricing baseline — must be kept in sync with the PostingDefault
# model field defaults. Whoever changes the model migration also updates this.
STOCK_PRICING_BASELINE = PricingDefaults(
    multiplier_low=2.0,
    multiplier_mid=1.8,
    multiplier_high=1.5,
    min_price=0.0,
    forced_ending=0.99,
    exchange_rate=None,
)


def build_pricing_rule(defaults: PricingDefaults) -> LibPricingRule:
    """Convert a PricingDefaults into a library-level PricingRule."""
    return LibPricingRule(
        multiplier_low=defaults.multiplier_low,
        multiplier_mid=defaults.multiplier_mid,
        multiplier_high=defaults.multiplier_high,
        min_price=defaults.min_price,
        forced_ending=defaults.forced_ending,
    )
