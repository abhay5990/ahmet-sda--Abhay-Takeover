"""Roblox account slice."""

from .resolver import RobloxResolver
from .content import RobloxComposer
from .sources import RobloxLztSourceAdapter
from .marketplaces import RobloxEldoradoBuilder, RobloxGameBoostBuilder, RobloxG2GBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="roblox",
            category=ListingCategory.ACCOUNT,
            resolver=RobloxResolver(),
            composer=RobloxComposer(),
            marketplaces={
                "eldorado": RobloxEldoradoBuilder(),
                "gameboost": RobloxGameBoostBuilder(),
                "g2g": RobloxG2GBuilder(),
            },
        )
    )


__all__ = [
    "RobloxComposer",
    "RobloxEldoradoBuilder",
    "RobloxGameBoostBuilder",
    "RobloxG2GBuilder",
    "RobloxLztSourceAdapter",
    "RobloxResolver",
    "register",
]
