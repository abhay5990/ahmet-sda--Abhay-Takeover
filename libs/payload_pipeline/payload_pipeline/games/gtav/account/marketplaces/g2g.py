"""G2G builder for resolved GTA V accounts.

brand_id ``lgc_game_24333`` and the ``lgc_24333_platform`` collection are the
seller-wide G2G configuration shared by **all** games in this repo (Brawl Stars,
Valorant, Roblox, CS2, Fortnite, etc.).  They are not game-specific.

The platform dataset is fixed to ``Android`` (``lgc_24333_platform_26098``) as a
deterministic legacy fallback.  The old builder randomly chose between Android and
IOS; both are accepted by the G2G API for any game.
"""

from __future__ import annotations

from typing import Any

from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_24333"
# Deterministic legacy fallback: always use Android.
# Both Android and IOS are accepted by the G2G API for all games.
_PLATFORM_DATASET_ID = "lgc_24333_platform_26098"


class GtavG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the GTA V account slice."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    def _build_offer_attributes(
        self,
        subject: Any,
    ) -> list[dict[str, str]]:
        return [
            {
                "collection_id": "lgc_24333_platform",
                "dataset_id": _PLATFORM_DATASET_ID,
            }
        ]
