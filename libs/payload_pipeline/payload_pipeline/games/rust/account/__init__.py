"""Rust account slice."""

from .resolver import RustResolver
from .content import RustComposer
from .manual_fields import RUST_MANUAL_FIELDS  # noqa: F401 — triggers registration
from .media import RustMediaStrategy
from .sources import RustManualSourceAdapter
from .marketplaces import RustEldoradoBuilder, RustGameBoostBuilder, RustPlayerAuctionsBuilder
from ....marketplaces.u7buy import U7BuyAccountBuilder
from ....core.enums import ListingCategory
from ....core.registry import GameDefinition


def register(registry) -> None:
    registry.register_game(
        GameDefinition(
            game="rust",
            category=ListingCategory.ACCOUNT,
            resolver=RustResolver(),
            composer=RustComposer(),
            media_strategy=RustMediaStrategy(),
            marketplaces={
                "eldorado": RustEldoradoBuilder(),
                "gameboost": RustGameBoostBuilder(),
                "playerauctions": RustPlayerAuctionsBuilder(),
                "u7buy": U7BuyAccountBuilder("rust"),
            },
        )
    )


__all__ = [
    "RustComposer",
    "RustEldoradoBuilder",
    "RustGameBoostBuilder",
    "RustManualSourceAdapter",
    "RustMediaStrategy",
    "RustPlayerAuctionsBuilder",
    "RustResolver",
    "register",
]
