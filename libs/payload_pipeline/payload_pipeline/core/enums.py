"""Type-safe enumerations for payload_pipeline.

Using ``str, Enum`` so that existing string comparisons work naturally.
Values match the canonical slugs from ``backend/data/game_mapp.json``
so that a single slug system is used across the entire codebase.
"""

from __future__ import annotations

from enum import Enum


class GameSlug(str, Enum):
    """Registry keys for supported games.

    Values are the canonical slugs from game_mapp.json.
    """

    R6 = "rainbow-six-siege"
    CS2 = "counter-strike-2"
    VAL = "valorant"
    BS = "brawl-stars"
    COC = "clash-of-clans"
    CR = "clash-royale"
    FN = "fortnite"
    GI = "genshin-impact"
    GTAV = "grand-theft-auto-5"
    LOL = "league-of-legends"
    ROBLOX = "roblox"
    STEAM = "steam"
    UBISOFT_CONNECT = "ubisoft-connect"


class Marketplace(str, Enum):
    """Supported marketplace identifiers."""

    ELDORADO = "eldorado"
    G2G = "g2g"
    GAMEBOOST = "gameboost"
    PLAYERAUCTIONS = "playerauctions"


class ListingCategory(str, Enum):
    """What is being listed — account or item."""

    ACCOUNT = "account"
    ITEM = "item"


class ListingKind(str, Enum):
    """How the listing is fulfilled — stock or dropshipping."""

    STOCK = "stock"
    DROPSHIPPING = "dropshipping"
