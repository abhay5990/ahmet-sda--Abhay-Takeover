"""Valorant account slice."""

from .content import ValorantComposer
from .marketplaces import (
    ValorantEldoradoBuilder,
    ValorantG2GBuilder,
    ValorantGameBoostBuilder,
    ValorantPlayerAuctionsBuilder,
)
from .media import ValorantMediaStrategy
from .resolver import ValorantResolver
from .sources import ValorantLztSourceAdapter
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="valorant",
            category=ListingCategory.ACCOUNT,
            resolver=ValorantResolver(),
            composer=ValorantComposer(),
            media_strategy=ValorantMediaStrategy(),
            marketplaces={
                "eldorado": ValorantEldoradoBuilder(),
                "g2g": ValorantG2GBuilder(),
                "gameboost": ValorantGameBoostBuilder(),
                "playerauctions": ValorantPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "ValorantComposer",
    "ValorantEldoradoBuilder",
    "ValorantG2GBuilder",
    "ValorantGameBoostBuilder",
    "ValorantPlayerAuctionsBuilder",
    "ValorantLztSourceAdapter",
    "ValorantMediaStrategy",
    "ValorantResolver",
    "register",
]
