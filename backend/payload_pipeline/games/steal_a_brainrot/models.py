"""Steal-A-Brainrot resolved item model."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SabResolvedItem:
    """Fully resolved SAB item ready for composition and building."""
    # Source identity
    offer_id: str
    source_url: str = ""

    # Item attributes
    item_name: str = ""
    rarity: str = ""
    ms_min: float = 0.0
    ms_max: float = 0.0
    mutations: list = field(default_factory=list)

    # Pricing
    price: float = 0.0
    quantity: int = 1

    # Media
    image_url: str = ""

    # Pipeline meta
    kind: str = "dropshipping"
    ref_key: str = ""
