"""Forza Horizon 5 account slice."""

from .resolver import Fh5Resolver
from .content import Fh5Composer
from .manual_fields import FH5_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .media import Fh5MediaStrategy
from .sources import Fh5ManualSourceAdapter
from .marketplaces import Fh5EldoradoBuilder, Fh5GameBoostBuilder, Fh5PlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="forza-horizon-5",
            category=ListingCategory.ACCOUNT,
            resolver=Fh5Resolver(),
            composer=Fh5Composer(),
            media_strategy=Fh5MediaStrategy(),
            marketplaces={
                "eldorado": Fh5EldoradoBuilder(),
                "gameboost": Fh5GameBoostBuilder(),
                "playerauctions": Fh5PlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "Fh5Composer",
    "Fh5EldoradoBuilder",
    "Fh5GameBoostBuilder",
    "Fh5ManualSourceAdapter",
    "Fh5MediaStrategy",
    "Fh5PlayerAuctionsBuilder",
    "Fh5Resolver",
    "register",
]
