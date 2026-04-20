"""Shared catalog primitives for game content prioritization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValuableItem:
    """A named cosmetic item with a category label.

    The priority of an item is determined solely by its position in the
    containing list — earlier index = higher priority.  No numeric tier
    field is needed; list order is the single source of truth.

    ``category`` is used for display grouping in descriptions
    (e.g. "outfit", "pickaxe", "emote", "glider" for Fortnite;
    "melee", "vandal", "phantom" for Valorant).
    """

    name: str
    category: str
