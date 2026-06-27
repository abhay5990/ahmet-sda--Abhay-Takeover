"""Clash of Clans account slice."""

from .marketplaces import (
    CocEldoradoBuilder,
    CocG2GBuilder,
    CocGameBoostBuilder,
    CocPlayerAuctionsBuilder,
)
from .resolver import CocResolver
from .content import CocComposer
from .media import CocMediaStrategy
from .manual_fields import COC_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .sources import CocLztSourceAdapter, CocTrackerSourceAdapter
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="clash-of-clans",
            category=ListingCategory.ACCOUNT,
            resolver=CocResolver(),
            composer=CocComposer(),
            media_strategy=CocMediaStrategy(),
            marketplaces={
                "eldorado": CocEldoradoBuilder(),
                "g2g": CocG2GBuilder(),
                "gameboost": CocGameBoostBuilder(),
                "playerauctions": CocPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "CocComposer",
    "CocMediaStrategy",
    "CocEldoradoBuilder",
    "CocG2GBuilder",
    "CocGameBoostBuilder",
    "CocLztSourceAdapter",
    "CocPlayerAuctionsBuilder",
    "CocTrackerSourceAdapter",
    "CocResolver",
    "register",
]
