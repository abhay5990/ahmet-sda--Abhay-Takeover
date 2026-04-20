"""G2G builder for resolved Fortnite accounts (stock only)."""

from __future__ import annotations

from typing import Any

from ..models import FortniteResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_24742"

# Collection IDs
_COL_RANK = "01e2f0e3"
_COL_OUTFITS = "60ef7ea7"
_COL_PICKAXES = "79da0454"
_COL_GLIDERS = "5bf6ebe1"
_COL_EMOTES = "e0b3a947"

# Rank dataset mappings
_RANK_MAP = {
    "Unreal": "14e9f56b",
    "Champion": "4d2c7a66",
    "Elite": "29ba0eaa",
    "Diamond": "63ff888a",
    "Platinum": "95fd7e1b",
    "Gold": "dcdc6511",
    "Silver": "c74bd50e",
    "Bronze": "f1858c92",
}

# Outfits count -> dataset_id (thresholds checked descending)
_OUTFITS_THRESHOLDS = [
    (1000, "a4f45fe1"), (700, "26b52e53"), (500, "9cfcc42b"), (300, "b69e5cfa"),
    (100, "b760e9e5"), (50, "8e63a5f4"), (30, "a53f0f6d"), (10, "bdad64b8"),
]
_OUTFITS_DEFAULT = "a5f3c999"  # 9 or below

# Pickaxes count -> dataset_id
_PICKAXES_THRESHOLDS = [
    (500, "d9a6f79e"), (300, "62ee9c4f"), (100, "31e0e43e"), (70, "3d3e1343"),
    (50, "05e5cfb5"), (30, "d91b5e4a"), (10, "5f912236"),
]
_PICKAXES_DEFAULT = "09d63a9a"  # 9 or below


class FortniteG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the Fortnite account slice (stock only)."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    @property
    def _include_softpin(self) -> bool:
        return False

    def _round_price(self, price: float) -> float:
        return price

    def _build_offer_attributes(self, subject: Any) -> list[dict[str, str]]:
        account: FortniteResolvedAccount = subject
        attrs: list[dict[str, str]] = []

        # 1. Rank -- not available from LZT, default to Diamond
        attrs.append({"collection_id": _COL_RANK, "dataset_id": _RANK_MAP["Diamond"]})

        # 2. Outfits count
        attrs.append({
            "collection_id": _COL_OUTFITS,
            "dataset_id": _threshold_lookup(account.skin_count, _OUTFITS_THRESHOLDS, _OUTFITS_DEFAULT),
        })

        # 3. Pickaxes count
        attrs.append({
            "collection_id": _COL_PICKAXES,
            "dataset_id": _threshold_lookup(account.pickaxe_count, _PICKAXES_THRESHOLDS, _PICKAXES_DEFAULT),
        })

        # 4. Gliders (numeric value)
        attrs.append({"collection_id": _COL_GLIDERS, "value": str(account.glider_count)})

        # 5. Emotes (numeric value)
        attrs.append({"collection_id": _COL_EMOTES, "value": str(account.dance_count)})

        return attrs

    def prepare_softpin_data(self, account: FortniteResolvedAccount) -> str:
        return self._build_softpin(account.credentials)


def _threshold_lookup(
    value: int,
    thresholds: list[tuple[int, str]],
    default: str,
) -> str:
    for threshold, dataset_id in thresholds:
        if value >= threshold:
            return dataset_id
    return default
