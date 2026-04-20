"""R6 account slice."""

from .content import R6Composer
from .marketplaces import R6EldoradoBuilder, R6GameBoostBuilder
from .media import R6MediaStrategy
from .resolver import R6Resolver
from .sources import R6LztSourceAdapter, R6TrackerSourceAdapter
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="rainbow-six-siege",
            category=ListingCategory.ACCOUNT,
            resolver=R6Resolver(),
            composer=R6Composer(),
            media_strategy=R6MediaStrategy(),
            marketplaces={
                "eldorado": R6EldoradoBuilder(),
                "gameboost": R6GameBoostBuilder(),
            },
        )
    )


__all__ = [
    "R6Composer",
    "R6EldoradoBuilder",
    "R6GameBoostBuilder",
    "R6LztSourceAdapter",
    "R6MediaStrategy",
    "R6Resolver",
    "R6TrackerSourceAdapter",
    "register",
]
