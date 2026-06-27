"""Steam account slice."""

from .manual_fields import STEAM_MANUAL_FIELDS  # noqa: F401
from .resolver import SteamResolver
from .content import SteamComposer
from .media import SteamMediaStrategy
from .sources import SteamLztSourceAdapter
from .marketplaces import SteamEldoradoBuilder, SteamGameBoostBuilder, SteamG2GBuilder, SteamPlayerAuctionsBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="steam",
            category=ListingCategory.ACCOUNT,
            resolver=SteamResolver(),
            composer=SteamComposer(),
            media_strategy=SteamMediaStrategy(),
            marketplaces={
                "eldorado": SteamEldoradoBuilder(),
                "gameboost": SteamGameBoostBuilder(),
                "g2g": SteamG2GBuilder(),
                "playerauctions": SteamPlayerAuctionsBuilder(),
            },
        )
    )


__all__ = [
    "SteamComposer",
    "SteamEldoradoBuilder",
    "SteamGameBoostBuilder",
    "SteamG2GBuilder",
    "SteamPlayerAuctionsBuilder",
    "SteamMediaStrategy",
    "SteamLztSourceAdapter",
    "SteamResolver",
    "register",
]
