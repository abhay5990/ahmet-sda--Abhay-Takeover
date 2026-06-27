"""New World account slice (Eldorado + PlayerAuctions)."""

from .resolver import NwAccountResolver
from .content import NwAccountComposer
from .manual_fields import NW_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .media import NwAccountMediaStrategy
from .sources import NwManualSourceAdapter
from .marketplaces import NwEldoradoBuilder, NwPlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="new-world",
            category=ListingCategory.ACCOUNT,
            resolver=NwAccountResolver(),
            composer=NwAccountComposer(),
            media_strategy=NwAccountMediaStrategy(),
            marketplaces={
                "eldorado": NwEldoradoBuilder(),
                "playerauctions": NwPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "NwAccountComposer",
    "NwAccountMediaStrategy",
    "NwAccountResolver",
    "NwEldoradoBuilder",
    "NwManualSourceAdapter",
    "NwPlayerAuctionsBuilder",
    "register",
]
