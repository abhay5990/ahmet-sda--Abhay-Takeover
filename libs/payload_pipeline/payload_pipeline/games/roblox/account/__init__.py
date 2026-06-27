"""Roblox account slice."""

from .resolver import RobloxResolver
from .content import RobloxComposer
from .media import RobloxMediaStrategy
from .manual_fields import ROBLOX_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .sources import RobloxLztSourceAdapter
from .marketplaces import RobloxEldoradoBuilder, RobloxGameBoostBuilder, RobloxG2GBuilder, RobloxPlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="roblox",
            category=ListingCategory.ACCOUNT,
            resolver=RobloxResolver(),
            composer=RobloxComposer(),
            media_strategy=RobloxMediaStrategy(),
            marketplaces={
                "eldorado": RobloxEldoradoBuilder(),
                "gameboost": RobloxGameBoostBuilder(),
                "g2g": RobloxG2GBuilder(),
                "playerauctions": RobloxPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "RobloxComposer",
    "RobloxEldoradoBuilder",
    "RobloxGameBoostBuilder",
    "RobloxG2GBuilder",
    "RobloxPlayerAuctionsBuilder",
    "RobloxLztSourceAdapter",
    "RobloxMediaStrategy",
    "RobloxResolver",
    "register",
]
