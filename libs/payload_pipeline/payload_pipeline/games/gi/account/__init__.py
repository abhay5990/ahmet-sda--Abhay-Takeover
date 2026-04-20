"""Genshin Impact account slice."""

from .resolver import GenshinResolver
from .content import GenshinComposer
from .sources import GenshinLztSourceAdapter
from .marketplaces import (
    GenshinImpactEldoradoBuilder,
    GenshinImpactGameBoostBuilder,
    GenshinImpactPlayerAuctionsBuilder,
)
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="genshin-impact",
            category=ListingCategory.ACCOUNT,
            resolver=GenshinResolver(),
            composer=GenshinComposer(),
            marketplaces={
                "eldorado": GenshinImpactEldoradoBuilder(),
                "gameboost": GenshinImpactGameBoostBuilder(),
                "playerauctions": GenshinImpactPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "GenshinComposer",
    "GenshinImpactEldoradoBuilder",
    "GenshinImpactGameBoostBuilder",
    "GenshinImpactPlayerAuctionsBuilder",
    "GenshinLztSourceAdapter",
    "GenshinResolver",
    "register",
]
