"""Ubisoft Connect account slice."""

from .manual_fields import UBISOFT_MANUAL_FIELDS  # noqa: F401
from .resolver import UbisoftResolver
from .content import UbisoftComposer
from .media import UbisoftMediaStrategy
from .sources import UbisoftLztSourceAdapter
from .marketplaces import (
    UbisoftEldoradoBuilder,
    UbisoftGameBoostBuilder,
    UbisoftPlayerAuctionsBuilder,
)
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="ubisoft-connect",
            category=ListingCategory.ACCOUNT,
            resolver=UbisoftResolver(),
            composer=UbisoftComposer(),
            media_strategy=UbisoftMediaStrategy(),
            marketplaces={
                "eldorado": UbisoftEldoradoBuilder(),
                "gameboost": UbisoftGameBoostBuilder(),
                "playerauctions": UbisoftPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "UbisoftComposer",
    "UbisoftEldoradoBuilder",
    "UbisoftGameBoostBuilder",
    "UbisoftMediaStrategy",
    "UbisoftLztSourceAdapter",
    "UbisoftPlayerAuctionsBuilder",
    "UbisoftResolver",
    "register",
]
