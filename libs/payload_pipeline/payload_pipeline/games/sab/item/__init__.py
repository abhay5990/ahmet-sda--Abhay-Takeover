"""Steal-A-Brainrot item slice."""
from .resolver import SabItemResolver
from .content import SabItemComposer
from .media import SabItemMediaStrategy
from .marketplaces import SabItemGameBoostBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="steal-a-brainrot",
            category=ListingCategory.ITEM,
            resolver=SabItemResolver(),
            composer=SabItemComposer(),
            media_strategy=SabItemMediaStrategy(),
            marketplaces={
                "gameboost": SabItemGameBoostBuilder(),
            },
        )
    )


__all__ = [
    "SabItemComposer",
    "SabItemGameBoostBuilder",
    "SabItemMediaStrategy",
    "SabItemResolver",
    "register",
]
