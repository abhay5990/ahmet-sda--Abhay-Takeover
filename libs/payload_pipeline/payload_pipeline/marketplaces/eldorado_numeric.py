"""Eldorado Numeric account attributes (required since late Oct 2026).

Eldorado's account form now requires exact numbers next to the old dropdown
buckets (e.g. Fortnite skin count next to "50-99"). The ids, ranges and
precision below are the live account-form schema captured on 22 Oct 2026 and
in production use by MCT (``server/eldoradoOfferAttributes.ts``).

Values that Eldorado expresses in thousands (V-Bucks, Blue Essence, Robux,
gems, trophies, Rust hours, primogems, renown, Valorant points, premier rating)
are sent as ``round(value / 1000, 1)`` — use :func:`thousand`.

Every number comes from the same resolved-account field the game's dropdown
bucket already uses; nothing is estimated. A value outside Eldorado's range
or precision raises :class:`EldoradoNumericAttributeError` so the listing is
held instead of being silently changed.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# id -> (minimum, maximum, decimals)   decimals 0 = integer
ELDORADO_NUMERIC_SPECS: dict[str, tuple[float, float, int]] = {
    "fortnite-emotes-numeric": (0, 1700, 0),
    "fortnite-outfits-skins-numeric": (0, 2800, 0),
    "fortnite-pickaxes-numeric": (0, 2300, 0),
    "fortnite-v-bucks-numeric": (0, 50, 1),
    "valorant-agents-numeric": (0, 30, 0),
    "valorant-knives-numeric": (0, 170, 0),
    "valorant-spent-points-numeric": (0, 300, 1),
    "valorant-weapon-skins-numeric": (0, 1350, 0),
    "league-of-legends-blue-essence-numeric": (0, 250, 1),
    "league-of-legends-champion-count-numeric": (0, 174, 0),
    "league-of-legends-riot-points-numeric": (0, 50, 1),
    "league-of-legends-skins-numeric": (0, 1500, 0),
    "rainbow-six-siege-x-black-ice-skins-numeric": (0, 100, 0),
    "rainbow-six-siege-x-operators-numeric": (0, 80, 0),
    "rainbow-six-siege-x-renown-numeric": (0, 500, 1),
    "clash-of-clans-gems-numeric": (0, 250, 1),
    "clash-of-clans-town-hall-numeric": (1, 18, 0),
    "brawl-stars-brawlers-count-numeric": (1, 110, 0),
    "brawl-stars-buffies-numeric": (0, 400, 0),
    "brawl-stars-gems-numeric": (0, 100, 1),
    "brawl-stars-hypercharge-numeric": (0, 110, 0),
    "brawl-stars-maxed-brawlers-numeric": (0, 110, 0),
    "brawl-stars-prestige-numeric": (0, 300, 0),
    "brawl-stars-skins-numeric": (0, 1200, 0),
    "brawl-stars-trophies-numeric": (0, 300, 1),
    "roblox-inventory-value-numeric": (0, 300, 1),
    "roblox-offsale-items-numeric": (0, 1000, 0),
    "roblox-robux-balance-numeric": (0, 300, 1),
    "minecraft-hypixel-level-numeric": (0, 250, 0),
    "cs2-faceit-level-numeric": (0, 10, 0),
    "cs2-medals-numeric": (0, 40, 0),
    "cs2-premier-rating-numeric": (0, 35, 1),
    "rust-hours-played-numeric": (0, 40, 1),
    "rust-skins-count-numeric": (0, 5000, 0),
    "rust-steam-account-level-numeric": (0, 6000, 0),
    "genshin-impact-adventure-rank-numeric": (1, 60, 0),
    "genshin-impact-characters-numeric": (1, 115, 0),
    "genshin-impact-events-count-numeric": (0, 200, 0),
    "genshin-impact-legendary-weapons-numeric": (0, 60, 0),
    "genshin-impact-primogems-count-numeric": (0, 150, 1),
}


class EldoradoNumericAttributeError(ValueError):
    """A required Numeric attribute cannot be sent truthfully."""

    def __init__(self, attribute_id: str, message: str) -> None:
        super().__init__(f"Eldorado Numeric attribute '{attribute_id}': {message}")
        self.attribute_id = attribute_id


def count(value: Any) -> int:
    """A literal counter (negative source values mean 'none' → 0)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return max(0, int(round(number)))


def thousand(value: Any) -> float:
    """Thousand-denominated field: 2650 → 2.7, 73825 → 73.8 (negatives → 0).

    Rounds half-up exactly like MCT/Eldorado (``Math.round(v / 100) / 10``);
    Python's ``round(2.65, 1)`` would give 2.6.
    """
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
    if not number.is_finite() or number <= 0:
        return 0.0
    return float((number / 1000).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def is_numeric_attribute(attribute_id: str) -> bool:
    return attribute_id in ELDORADO_NUMERIC_SPECS


def validate_numeric(attribute_id: str, value: Any) -> int | float:
    """Return the exact provider value or raise (never clamps or rounds silently)."""
    spec = ELDORADO_NUMERIC_SPECS.get(attribute_id)
    if spec is None:
        raise EldoradoNumericAttributeError(attribute_id, "unknown Numeric attribute id")
    minimum, maximum, decimals = spec
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EldoradoNumericAttributeError(attribute_id, f"value {value!r} is not a finite number")
    if value < minimum or value > maximum:
        raise EldoradoNumericAttributeError(
            attribute_id, f"value {value} is outside Eldorado's range {minimum}..{maximum}",
        )
    if decimals == 0:
        if float(value) != int(value):
            raise EldoradoNumericAttributeError(attribute_id, f"value {value} must be a whole number")
        return int(value)
    if round(float(value), decimals) != float(value):
        raise EldoradoNumericAttributeError(attribute_id, f"value {value} has more than {decimals} decimal(s)")
    return float(value)


def serialize_attributes(
    select_attributes: dict[str, str] | None,
    numeric_attributes: dict[str, int | float] | None,
) -> list[dict[str, Any]]:
    """Typed ``augmentedGame.offerAttributes`` array (Select first, then Numeric)."""
    out: list[dict[str, Any]] = []
    for attr_id, value in (select_attributes or {}).items():
        out.append({"id": attr_id, "type": "Select", "value": value})
    for attr_id, value in (numeric_attributes or {}).items():
        out.append({"id": attr_id, "type": "Numeric", "value": validate_numeric(attr_id, value)})
    return out
