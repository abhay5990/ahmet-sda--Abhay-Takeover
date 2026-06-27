"""Xbox account slice."""

from .manual_fields import XBOX_MANUAL_FIELDS  # noqa: F401
from .resolver import XboxResolver
from .content import XboxComposer
from .media import XboxMediaStrategy
from .sources import XboxManualSourceAdapter
from .marketplaces import XboxEldoradoBuilder, XboxPlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="xbox",
            category=ListingCategory.ACCOUNT,
            resolver=XboxResolver(),
            composer=XboxComposer(),
            media_strategy=XboxMediaStrategy(),
            marketplaces={
                "eldorado": XboxEldoradoBuilder(),
                "playerauctions": XboxPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "XboxComposer",
    "XboxEldoradoBuilder",
    "XboxManualSourceAdapter",
    "XboxMediaStrategy",
    "XboxPlayerAuctionsBuilder",
    "XboxResolver",
    "register",
]
