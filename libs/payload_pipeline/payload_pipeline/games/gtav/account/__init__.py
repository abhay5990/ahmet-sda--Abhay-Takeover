"""GTA V account slice."""

from .manual_fields import GTAV_MANUAL_FIELDS  # noqa: F401
from .resolver import GtavResolver
from .content import GtavComposer
from .media import GtavMediaStrategy
from .sources import GtavManualSourceAdapter
from .marketplaces import (
    GtavEldoradoBuilder,
    GtavG2GBuilder,
    GtavGameBoostBuilder,
    GtavPlayerAuctionsBuilder,
)
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="grand-theft-auto-5",
            category=ListingCategory.ACCOUNT,
            resolver=GtavResolver(),
            composer=GtavComposer(),
            media_strategy=GtavMediaStrategy(),
            marketplaces={
                "eldorado": GtavEldoradoBuilder(),
                "g2g": GtavG2GBuilder(),
                "gameboost": GtavGameBoostBuilder(),
                "playerauctions": GtavPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "GtavComposer",
    "GtavEldoradoBuilder",
    "GtavG2GBuilder",
    "GtavGameBoostBuilder",
    "GtavManualSourceAdapter",
    "GtavMediaStrategy",
    "GtavPlayerAuctionsBuilder",
    "GtavResolver",
    "register",
]
