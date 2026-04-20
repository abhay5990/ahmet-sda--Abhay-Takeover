"""G2G builder for resolved Roblox accounts (stock only)."""

from __future__ import annotations

import random
from typing import Any

from ..models import RobloxResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_24333"


class RobloxG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the Roblox account slice (stock only)."""

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
        platform_options = [
            ("Android", "lgc_24333_platform_26098"),
            ("IOS", "lgc_24333_platform_26099"),
        ]
        _platform_value, platform_dataset_id = random.choice(platform_options)
        return [
            {
                "collection_id": "lgc_24333_platform",
                "dataset_id": platform_dataset_id,
            }
        ]

    def prepare_softpin_data(self, account: RobloxResolvedAccount) -> str:
        return self._build_softpin(account.credentials)
