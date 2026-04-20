"""G2G builder for resolved Clash Royale accounts."""

from __future__ import annotations

from typing import Any

from ..models import CrResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_23420"

_COLLECTION_KING_LEVEL = "8c84e786"
_COLLECTION_ARENA = "424230f4"
_COLLECTION_LVL15_CARDS = "527fd9b8"
_COLLECTION_LVL14_CARDS = "e6ae1ea1"

_KING_LEVEL_MAP = {
    70: "72693018",
    65: "38631ed5",
    60: "2896f149",
    50: "759e22ce",
    40: "5211f623",
    30: "59b5659d",
    20: "12ebf76f",
    10: "e73b5555",
}
_ARENA_MAP = {
    "Legendary Arena": "623ebc4f",
    "PANCAKES!": "752d96c9",
    "Clash Fest": "44418071",
    "Boot Camp": "4b06ecad",
    "Spell Valley": "515f87c5",
    "Lumberlove Cabin": "752d96c9",
}
_LVL15_CARDS_MAP = {
    110: "bed46c2d",
    90: "a1452c03",
    70: "78a64276",
    50: "4b54b0bd",
    30: "e7d00a8a",
    10: "cbb8a51f",
}
_LVL14_CARDS_MAP = {
    110: "023f4275",
    90: "faee80f2",
    70: "eb84df29",
    50: "623a0805",
    30: "46f5e821",
    10: "1271b19e",
}


class CrG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the Clash Royale account slice."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    def _build_offer_attributes(self, subject: Any) -> list[dict[str, str]]:
        account: CrResolvedAccount = subject
        return [
            {
                "collection_id": _COLLECTION_KING_LEVEL,
                "dataset_id": self._range_dataset(account.king_level, _KING_LEVEL_MAP, "e40b8a49"),
            },
            {
                "collection_id": _COLLECTION_ARENA,
                "dataset_id": _ARENA_MAP.get(account.arena_name, "515f87c5"),
            },
            {
                "collection_id": _COLLECTION_LVL15_CARDS,
                "dataset_id": self._range_dataset(
                    account.level_15_cards_count,
                    _LVL15_CARDS_MAP,
                    "940cdc6c",
                ),
            },
            {
                "collection_id": _COLLECTION_LVL14_CARDS,
                "dataset_id": self._range_dataset(
                    account.level_14_cards_count,
                    _LVL14_CARDS_MAP,
                    "19fd81df",
                ),
            },
        ]

    @staticmethod
    def _range_dataset(value: int, mapping: dict[int, str], default: str) -> str:
        for threshold in sorted(mapping.keys(), reverse=True):
            if value >= threshold:
                return mapping[threshold]
        return default
