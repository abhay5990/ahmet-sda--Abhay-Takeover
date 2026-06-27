"""PSN account slice."""

from .manual_fields import PSN_MANUAL_FIELDS  # noqa: F401
from .resolver import PsnResolver
from .content import PsnComposer
from .media import PsnMediaStrategy
from .sources import PsnManualSourceAdapter
from .marketplaces import PsnEldoradoBuilder, PsnPlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="playstation",
            category=ListingCategory.ACCOUNT,
            resolver=PsnResolver(),
            composer=PsnComposer(),
            media_strategy=PsnMediaStrategy(),
            marketplaces={
                "eldorado": PsnEldoradoBuilder(),
                "playerauctions": PsnPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "PsnComposer",
    "PsnEldoradoBuilder",
    "PsnManualSourceAdapter",
    "PsnMediaStrategy",
    "PsnPlayerAuctionsBuilder",
    "PsnResolver",
    "register",
]
