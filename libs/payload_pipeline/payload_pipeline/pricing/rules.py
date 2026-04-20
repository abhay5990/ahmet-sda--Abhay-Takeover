"""Pure, immutable pricing logic for payload_pipeline.

No singletons, no mutable state, no config manager.
Rules are passed in from the caller (typically via request.context).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PricingRule:
    """Immutable pricing parameters for a single marketplace."""

    multiplier_low: float = 2.0   # price <= 10
    multiplier_mid: float = 2.0   # 10 < price <= 100
    multiplier_high: float = 2.0  # price > 100
    min_price: float = 0.0
    forced_ending: float | None = None  # e.g. 0.99 → forces .99 ending

    def select_multiplier(self, raw_price: float) -> float:
        if raw_price <= 10:
            return self.multiplier_low
        if raw_price <= 100:
            return self.multiplier_mid
        return self.multiplier_high


def calculate_price(raw_price: float, rule: PricingRule | None) -> float:
    """Apply pricing rule to a raw price.

    Steps:
      1. Select the appropriate multiplier for the price range.
      2. Multiply and ceil.
      3. Round to 2 decimals.
      4. Apply min_price floor.
      5. Apply forced_ending if configured.

    Returns raw_price unchanged when *rule* is ``None``.
    """
    if rule is None:
        return raw_price

    multiplier = rule.select_multiplier(raw_price)
    price = math.ceil(raw_price * multiplier * 100) / 100  # ceil to 2 decimals
    price = round(price, 2)
    price = max(price, rule.min_price)

    if rule.forced_ending is not None:
        integer_part = int(price)
        price = integer_part + rule.forced_ending

    return price
