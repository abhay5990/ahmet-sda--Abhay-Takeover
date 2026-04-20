"""Game registrations for payload_pipeline."""

from .bs import register as register_bs
from .coc import register as register_coc
from .cr import register as register_cr
from .cs2 import register as register_cs2
from .fn import register as register_fortnite
from .gi import register as register_genshin
from .gtav import register as register_gtav
from .lol import register as register_lol
from .r6 import register as register_r6
from .roblox import register as register_roblox
from .steam import register as register_steam
from .ubisoft_connect import register as register_ubisoft
from .val import register as register_valorant


def register_supported_games(registry) -> None:
    """Register only games that have at least one marketplace builder.

    These slices are fully functional end-to-end: resolve → compose → build.
    Currently 13 supported slices.
    """
    register_r6(registry)
    register_cs2(registry)
    register_valorant(registry)
    register_bs(registry)
    register_coc(registry)
    register_cr(registry)
    register_fortnite(registry)
    register_genshin(registry)
    register_gtav(registry)
    register_lol(registry)
    register_roblox(registry)
    register_steam(registry)
    register_ubisoft(registry)


def register_experimental_games(registry) -> None:
    """Register incomplete/experimental slices (resolver + composer only, no builders).

    These slices can resolve and compose but cannot produce marketplace payloads.
    They are excluded from the default registry and require explicit opt-in.

    Currently empty — all slices have been promoted to supported.
    """
    pass


def register_default_games(registry) -> None:
    """Register all production-ready games (supported only).

    This is the standard entry point used by ``build_default_registry()``.
    Experimental slices without marketplace builders are excluded.
    Use ``register_experimental_games()`` to opt in explicitly.
    """
    register_supported_games(registry)


__all__ = [
    "register_default_games",
    "register_supported_games",
    "register_experimental_games",
]
