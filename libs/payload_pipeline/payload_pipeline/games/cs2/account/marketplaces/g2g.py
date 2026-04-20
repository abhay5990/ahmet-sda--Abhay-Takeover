"""G2G builder for resolved CS2 accounts (stock only)."""

from __future__ import annotations

from typing import Any

from ..models import CS2ResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


# G2G constants — same as legacy
_BRAND_ID = "lgc_game_22539"


class CS2G2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the CS2 account slice (stock only)."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    @property
    def _include_softpin(self) -> bool:
        return False

    def _round_price(self, price: float) -> float:
        return price

    def _build_offer_attributes(
        self,
        subject: Any,
    ) -> list[dict[str, str]]:
        return _build_offer_attributes_static(subject)

    def prepare_softpin_data(self, account: CS2ResolvedAccount) -> str:
        return self._build_softpin(account.credentials)


# ------------------------------------------------------------------
# Attribute mapping — dataset IDs match legacy exactly
# ------------------------------------------------------------------


def _build_offer_attributes_static(account: CS2ResolvedAccount) -> list[dict[str, str]]:
    return [
        # 1. Prime Status
        {
            "collection_id": "50af404e",
            "dataset_id": "25d9928f" if account.is_prime else "66431b9f",
        },
        # 2. Account Type (always Ranked Accounts)
        {
            "collection_id": "4cbb2c55",
            "dataset_id": "4ab10ae5",
        },
        # 3. Premier ELO
        {
            "collection_id": "b5ba5e2d",
            "dataset_id": _dataset_for_elo(account.premier_elo),
        },
        # 4. Competitive Rank
        {
            "collection_id": "ba1ca2e5",
            "dataset_id": _dataset_for_rank_id(account.rank_id),
        },
        # 5. Service Medals
        {
            "collection_id": "8a5e6cd6",
            "dataset_id": _dataset_for_medals(account.medal_count),
        },
    ]


# ------------------------------------------------------------------
# Dataset ID helpers — kept module-private, mirrors legacy 1:1
# ------------------------------------------------------------------


def _dataset_for_elo(elo: int) -> str:
    if elo >= 30000:
        return "9762e3c7"
    if elo >= 25000:
        return "1e176870"
    if elo >= 20000:
        return "7090e0f8"
    if elo >= 15000:
        return "1b7bfd08"
    if elo >= 10000:
        return "95871f79"
    if elo >= 5000:
        return "c0642e14"
    if elo >= 1:
        return "73fde4a8"
    return "249dd800"  # UnRated


_RANK_ID_TO_DATASET: dict[int, str] = {
    0: "7d397218",   # UnRanked
    1: "e651dde8", 2: "e651dde8", 3: "e651dde8",
    4: "e651dde8", 5: "e651dde8", 6: "e651dde8",   # Silver
    7: "61d844c6", 8: "61d844c6", 9: "61d844c6", 10: "61d844c6",  # Gold Nova
    11: "38b1679f", 12: "38b1679f",  # Master Guardian
    13: "547b39ec",  # Master Guardian Elite
    14: "6a89a15c",  # Distinguished MG
    15: "f4645f9e",  # Legendary Eagle
    16: "e481dcd2",  # Legendary Eagle Master
    17: "49af889e",  # Supreme Master
    18: "6c61f581",  # The Global Elite
}


def _dataset_for_rank_id(rank_id: int) -> str:
    return _RANK_ID_TO_DATASET.get(rank_id, "7d397218")


def _dataset_for_medals(medal_count: int) -> str:
    if medal_count >= 50:
        return "7ce240e4"
    if medal_count >= 40:
        return "0a4ee878"
    if medal_count >= 30:
        return "85957da6"
    if medal_count >= 20:
        return "8c3b1b3b"
    if medal_count >= 10:
        return "2659e8e8"
    if medal_count >= 6:
        return "2bd1eae0"
    return "4fefd16a"
