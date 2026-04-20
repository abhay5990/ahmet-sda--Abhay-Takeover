"""GTA V account slice."""

from .resolver import GtavResolver
from .content import GtavComposer
from .sources import GtavLztSourceAdapter
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
    "GtavLztSourceAdapter",
    "GtavPlayerAuctionsBuilder",
    "GtavResolver",
    "register",
]
