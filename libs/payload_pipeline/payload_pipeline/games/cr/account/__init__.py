"""Clash Royale account slice."""

from .marketplaces import (
    CrEldoradoBuilder,
    CrG2GBuilder,
    CrGameBoostBuilder,
    CrPlayerAuctionsBuilder,
)
from .resolver import CrResolver
from .content import CrComposer
from .media import CrMediaStrategy
from .sources import CrLztSourceAdapter, CrTrackerSourceAdapter
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="clash-royale",
            category=ListingCategory.ACCOUNT,
            resolver=CrResolver(),
            composer=CrComposer(),
            media_strategy=CrMediaStrategy(),
            marketplaces={
                "eldorado": CrEldoradoBuilder(),
                "g2g": CrG2GBuilder(),
                "gameboost": CrGameBoostBuilder(),
                "playerauctions": CrPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "CrComposer",
    "CrEldoradoBuilder",
    "CrG2GBuilder",
    "CrGameBoostBuilder",
    "CrMediaStrategy",
    "CrLztSourceAdapter",
    "CrPlayerAuctionsBuilder",
    "CrTrackerSourceAdapter",
    "CrResolver",
    "register",
]
