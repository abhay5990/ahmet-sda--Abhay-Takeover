"""CS2 account slice."""

from .content import CS2Composer
from .marketplaces import CS2EldoradoBuilder, CS2G2GBuilder, CS2GameBoostBuilder, CS2PlayerAuctionsBuilder
from .media import CS2MediaStrategy
from .resolver import CS2Resolver
from .manual_fields import CS2_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .sources import CS2LztSourceAdapter
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="counter-strike-2",
            category=ListingCategory.ACCOUNT,
            resolver=CS2Resolver(),
            composer=CS2Composer(),
            media_strategy=CS2MediaStrategy(),
            marketplaces={
                "eldorado": CS2EldoradoBuilder(),
                "gameboost": CS2GameBoostBuilder(),
                "g2g": CS2G2GBuilder(),
                "playerauctions": CS2PlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "CS2Composer",
    "CS2EldoradoBuilder",
    "CS2G2GBuilder",
    "CS2GameBoostBuilder",
    "CS2PlayerAuctionsBuilder",
    "CS2MediaStrategy",
    "CS2LztSourceAdapter",
    "CS2Resolver",
    "register",
]
