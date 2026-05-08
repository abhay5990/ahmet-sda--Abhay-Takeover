"""Fortnite account slice."""

from .resolver import FortniteResolver
from .content import FortniteComposer
from .media import FortniteMediaStrategy
from .sources import FortniteLztSourceAdapter
from .marketplaces import FortniteEldoradoBuilder, FortniteGameBoostBuilder, FortniteG2GBuilder, FortnitePlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="fortnite",
            category=ListingCategory.ACCOUNT,
            resolver=FortniteResolver(),
            composer=FortniteComposer(),
            media_strategy=FortniteMediaStrategy(),
            marketplaces={
                "eldorado": FortniteEldoradoBuilder(),
                "gameboost": FortniteGameBoostBuilder(),
                "g2g": FortniteG2GBuilder(),
                "playerauctions": FortnitePlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "FortniteComposer",
    "FortniteEldoradoBuilder",
    "FortniteGameBoostBuilder",
    "FortniteG2GBuilder",
    "FortnitePlayerAuctionsBuilder",
    "FortniteLztSourceAdapter",
    "FortniteMediaStrategy",
    "FortniteResolver",
    "register",
]
