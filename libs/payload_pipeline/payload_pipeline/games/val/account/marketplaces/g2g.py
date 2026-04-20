"""G2G builder for resolved Valorant accounts."""

from __future__ import annotations

import random
from typing import Any

from ..models import ValorantResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_24333"

_PLATFORM_OPTIONS = [
    ("Android", "lgc_24333_platform_26098"),
    ("IOS", "lgc_24333_platform_26099"),
]


class ValorantG2GBuilder(BaseG2GBuilder):
    """Flat, stateless G2G builder for the Valorant account slice."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    def _build_offer_attributes(
        self,
        subject: Any,
    ) -> list[dict[str, str]]:
        _, platform_dataset_id = random.choice(_PLATFORM_OPTIONS)
        return [
            {
                "collection_id": "lgc_24333_platform",
                "dataset_id": platform_dataset_id,
            },
        ]
