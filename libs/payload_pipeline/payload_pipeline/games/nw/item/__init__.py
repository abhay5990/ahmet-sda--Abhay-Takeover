"""New World item slice (GameBoost only)."""

from .resolver import NwItemResolver
from .content import NwItemComposer
from .media import NwItemMediaStrategy
from .sources import NwItemManualSourceAdapter
from .marketplaces import NwItemGameBoostBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="new-world",
            category=ListingCategory.ITEM,
            resolver=NwItemResolver(),
            composer=NwItemComposer(),
            media_strategy=NwItemMediaStrategy(),
            marketplaces={
                "gameboost": NwItemGameBoostBuilder(),
            },
        )
    )


__all__ = [
    "NwItemComposer",
    "NwItemGameBoostBuilder",
    "NwItemManualSourceAdapter",
    "NwItemMediaStrategy",
    "NwItemResolver",
    "register",
]
