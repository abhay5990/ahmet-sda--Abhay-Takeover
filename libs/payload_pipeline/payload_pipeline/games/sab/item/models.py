"""Steal-A-Brainrot resolved item model."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SabResolvedItem:
    offer_id: str
    source_url: str = ""
    item_name: str = ""
    rarity: str = ""
    ms_min: float = 0.0
    ms_max: float = 0.0
    mutations: list = field(default_factory=list)
    price: float = 0.0
    quantity: int = 1
    image_url: str = ""
    kind: str = "dropshipping"
    ref_key: str = ""
