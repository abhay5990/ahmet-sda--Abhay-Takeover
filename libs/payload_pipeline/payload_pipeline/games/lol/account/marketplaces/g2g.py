"""G2G builder for resolved League of Legends accounts."""

from __future__ import annotations

from typing import Any

from ..models import LolResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_22666"

# ── Verified G2G attribute mappings ─────────────────────────────────
# Source: test-data-g2g/lol-keyboard-relations.json
#
# Two verified collections:
#   Server   (e80c30d1) — dropdown, required
#   Account Type (319340f0) — dropdown, required
#
# The old builder also sent 3 "dependent" collections (eb7040e2, 04862150,
# 962f619a) that only appear when "Ranked Accounts" is selected.  We have
# no verified dataset-level mapping for those, so they are intentionally
# dropped.  G2G accepts offers with only the 2 required attributes.

_SERVER_COLLECTION_ID = "e80c30d1"
_ACCOUNT_TYPE_COLLECTION_ID = "319340f0"

# region (riot short code) -> G2G server dataset_id
# Built from keyboard-relations children entries.
_REGION_TO_SERVER_DATASET: dict[str, str] = {
    "NA1": "e2f2c55b",
    "EUW1": "304244a1",
    "EUN1": "1a87dd85",
    "LA1": "302ba1e6",
    "LA2": "f28899f5",
    "BR1": "31e5d298",
    "JP1": "e9926686",
    "RU": "77bc3c33",
    "TR1": "2247e703",
    "OC1": "5c030fef",
    "KR": "9f08d33e",
    "TW2": "93050187",
    "VN2": "075e1e09",
    "PBE": "444501ea",
}

# region_phrase (long name from LZT) -> G2G server dataset_id
_REGION_PHRASE_TO_SERVER_DATASET: dict[str, str] = {
    "North America": "e2f2c55b",
    "Europe West": "304244a1",
    "Europe Nordic & East": "1a87dd85",
    "Latin America North": "302ba1e6",
    "Latin America South": "f28899f5",
    "Middle East": "f86dd4b4",
    "Brazil": "31e5d298",
    "Japan": "e9926686",
    "Russia": "77bc3c33",
    "Turkey": "2247e703",
    "Oceania": "5c030fef",
    "Singapore, Malaysia & Indonesia": "67d20e31",
    "Thailand": "67d20e31",
    "Philippines": "67d20e31",
    "Vietnam": "075e1e09",
}

# Account Type classification rule:
# - If the account has a real ranked tier (not unranked/etc) -> "Ranked Accounts"
# - Otherwise -> "Smurf Accounts"
# This aligns with how G2G categorizes LoL offers: ranked accounts have a
# visible tier and are priced differently from fresh/unranked smurfs.
_SMURF_DATASET = "6380c8dd"
_RANKED_DATASET = "65ec9642"

_UNRANKED_VALUES = frozenset({
    "Unranked", "Ranked Ready", "Rank Ready", "No rank", "No Rank", "Unrated", "",
})


class LolG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the League of Legends account slice.

    Offer attributes use verified mappings from keyboard-relations.json.
    Only the 2 required collections (Server, Account Type) are sent.
    """

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    def _build_offer_attributes(self, subject: Any) -> list[dict[str, str]]:
        account: LolResolvedAccount = subject
        attrs: list[dict[str, str]] = []

        # Server — resolve from region (short code) first, fall back to region_phrase
        server_dataset = _REGION_TO_SERVER_DATASET.get(account.region)
        if not server_dataset:
            server_dataset = _REGION_PHRASE_TO_SERVER_DATASET.get(account.region_phrase)
        if server_dataset:
            attrs.append({
                "collection_id": _SERVER_COLLECTION_ID,
                "dataset_id": server_dataset,
            })

        # Account Type — ranked tier present -> Ranked, otherwise -> Smurf
        account_type_dataset = (
            _RANKED_DATASET
            if account.rank and account.rank not in _UNRANKED_VALUES
            else _SMURF_DATASET
        )
        attrs.append({
            "collection_id": _ACCOUNT_TYPE_COLLECTION_ID,
            "dataset_id": account_type_dataset,
        })

        return attrs
