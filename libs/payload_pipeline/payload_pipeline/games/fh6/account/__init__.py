"""Forza Horizon 6 account slice."""

from .resolver import Fh6Resolver
from .content import Fh6Composer
from .media import Fh6MediaStrategy
from .sources import Fh6ManualSourceAdapter
from .marketplaces import Fh6EldoradoBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="forza-horizon-6",
            category=ListingCategory.ACCOUNT,
            resolver=Fh6Resolver(),
            composer=Fh6Composer(),
            media_strategy=Fh6MediaStrategy(),
            marketplaces={
                "eldorado": Fh6EldoradoBuilder(),
            },
        )
    )


__all__ = [
    "Fh6Composer",
    "Fh6EldoradoBuilder",
    "Fh6ManualSourceAdapter",
    "Fh6MediaStrategy",
    "Fh6Resolver",
    "register",
]
