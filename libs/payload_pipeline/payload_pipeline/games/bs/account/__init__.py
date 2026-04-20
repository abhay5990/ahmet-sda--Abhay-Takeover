"""Brawl Stars account slice."""

from .marketplaces import (
    BSEldoradoBuilder,
    BSG2GBuilder,
    BSGameBoostBuilder,
    BSPlayerAuctionsBuilder,
)
from .resolver import BSResolver
from .content import BrawlStarsComposer
from .media import BSMediaStrategy
from .sources import BSLztSourceAdapter
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="brawl-stars",
            category=ListingCategory.ACCOUNT,
            resolver=BSResolver(),
            composer=BrawlStarsComposer(),
            media_strategy=BSMediaStrategy(),
            marketplaces={
                "eldorado": BSEldoradoBuilder(),
                "g2g": BSG2GBuilder(),
                "gameboost": BSGameBoostBuilder(),
                "playerauctions": BSPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "BrawlStarsComposer",
    "BSEldoradoBuilder",
    "BSG2GBuilder",
    "BSGameBoostBuilder",
    "BSMediaStrategy",
    "BSLztSourceAdapter",
    "BSPlayerAuctionsBuilder",
    "BSResolver",
    "register",
]
