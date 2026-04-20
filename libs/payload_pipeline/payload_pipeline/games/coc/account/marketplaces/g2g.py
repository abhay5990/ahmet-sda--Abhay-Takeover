"""G2G builder for resolved Clash of Clans accounts."""

from __future__ import annotations

from typing import Any

from ..models import CocResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_19955"

_COLLECTION_TH_LEVEL = "9b968823"
_COLLECTION_KING_LEVEL = "765fcca8"
_COLLECTION_QUEEN_LEVEL = "0528be31"
_COLLECTION_WARDEN_LEVEL = "0b103b6e"
_COLLECTION_CHAMPION_LEVEL = "f3342217"

_TH_LEVEL_MAP = {
    17: "fa1ae266",
    16: "1ec6a17c",
    15: "194a0552",
    14: "ed333b2d",
    13: "46496532",
    12: "a5f155bf",
    11: "973bec49",
    10: "d5fd31c4",
    9: "dd0f0e97",
    8: "57ff3312",
    7: "7e7b08db",
}
_KING_LEVEL_MAP = {
    100: "6078cb96",
    95: "8bda2ec6",
    90: "a1eaf199",
    85: "1db3d976",
    80: "3e1bab1f",
    75: "9c3aba69",
    70: "4839d371",
    50: "6293caa3",
    30: "a08d1d6e",
    10: "3c62d552",
}
_QUEEN_LEVEL_MAP = {
    100: "46c8f320",
    95: "2f521225",
    90: "f5b23357",
    85: "5974c877",
    80: "8d17bd47",
    75: "9a8c5487",
    70: "0329390c",
    50: "83816d33",
    30: "30471ed5",
    10: "edc44a70",
}
_WARDEN_LEVEL_MAP = {
    75: "2af5c1c4",
    70: "6e069c6a",
    65: "d4a8a908",
    60: "79a06712",
    50: "bbc7c579",
    30: "1892871e",
    10: "8091feb2",
}
_CHAMPION_LEVEL_MAP = {
    50: "e2a81a8d",
    45: "a3aab556",
    40: "95714651",
    35: "6f4fdc75",
    30: "3c6ed1db",
    20: "b194ed6f",
    10: "0242dc72",
}


class CocG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the Clash of Clans account slice."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    def _build_offer_attributes(self, subject: Any) -> list[dict[str, str]]:
        account: CocResolvedAccount = subject
        return [
            {
                "collection_id": _COLLECTION_TH_LEVEL,
                "dataset_id": self._exact_level_dataset(
                    account.town_hall_level,
                    _TH_LEVEL_MAP,
                    "435e46c6",
                ),
            },
            {
                "collection_id": _COLLECTION_KING_LEVEL,
                "dataset_id": self._range_dataset(
                    account.barbarian_king_level,
                    _KING_LEVEL_MAP,
                    "d8c00026",
                ),
            },
            {
                "collection_id": _COLLECTION_QUEEN_LEVEL,
                "dataset_id": self._range_dataset(
                    account.archer_queen_level,
                    _QUEEN_LEVEL_MAP,
                    "723bbdd7",
                ),
            },
            {
                "collection_id": _COLLECTION_WARDEN_LEVEL,
                "dataset_id": self._range_dataset(
                    account.grand_warden_level,
                    _WARDEN_LEVEL_MAP,
                    "3abee891",
                ),
            },
            {
                "collection_id": _COLLECTION_CHAMPION_LEVEL,
                "dataset_id": self._range_dataset(
                    account.royal_champion_level,
                    _CHAMPION_LEVEL_MAP,
                    "ba9b3133",
                ),
            },
        ]

    @staticmethod
    def _exact_level_dataset(value: int, mapping: dict[int, str], default: str) -> str:
        return mapping.get(value, default)

    @staticmethod
    def _range_dataset(value: int, mapping: dict[int, str], default: str) -> str:
        for threshold in sorted(mapping.keys(), reverse=True):
            if value >= threshold:
                return mapping[threshold]
        return default
