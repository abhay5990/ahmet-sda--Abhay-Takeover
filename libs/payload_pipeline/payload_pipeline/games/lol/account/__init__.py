"""League of Legends account slice."""

from .resolver import LolResolver
from .content import LolComposer
from .media import LolMediaStrategy
from .manual_fields import LOL_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .sources import LolLztSourceAdapter
from .marketplaces import (
    LolEldoradoBuilder,
    LolG2GBuilder,
    LolGameBoostBuilder,
    LolPlayerAuctionsBuilder,
)
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="league-of-legends",
            category=ListingCategory.ACCOUNT,
            resolver=LolResolver(),
            composer=LolComposer(),
            media_strategy=LolMediaStrategy(),
            marketplaces={
                "eldorado": LolEldoradoBuilder(),
                "g2g": LolG2GBuilder(),
                "gameboost": LolGameBoostBuilder(),
                "playerauctions": LolPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "LolComposer",
    "LolEldoradoBuilder",
    "LolG2GBuilder",
    "LolGameBoostBuilder",
    "LolMediaStrategy",
    "LolPlayerAuctionsBuilder",
    "LolLztSourceAdapter",
    "LolResolver",
    "register",
]
