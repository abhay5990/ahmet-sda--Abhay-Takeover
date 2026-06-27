"""Resolved models for the Rust slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class RustResolvedAccount(ResolvedAccountBase):
    """Single resolved Rust account after source normalization.

    Eldorado attribute IDs (Select type):
      premium-status: premium-yes | premium-no | premium-other
      rust-hours:     hours-099 | hours-100499 | hours-5001999 | hours-2000 | hours-other
      rust-skins:     skins-014 | skins-1549 | skins-5099 | skins-100 | skins-other
      steam-account-level: level-05 | level-624 | level-25 | level-other
    """

    platform: str = ""
    """Trade environment platform: PC, PlayStation, Xbox."""

    # Eldorado attribute IDs (predefined select values)
    premium_status: str = "premium-no"
    hours_range: str = "hours-099"
    skins_range: str = "skins-014"
    steam_level_range: str = "level-05"

    # GameBoost numeric values
    real_hours: int = 0
    skins_count: int = 0
    steam_level: int = 0

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "platform": FieldMeta("Account platform (PC / PlayStation / Xbox).", "PC"),
        "premium_status": FieldMeta("Premium status attribute ID.", "premium-no"),
        "hours_range": FieldMeta("Hours played range attribute ID.", "hours-099"),
        "skins_range": FieldMeta("Skins count range attribute ID.", "skins-014"),
        "steam_level_range": FieldMeta("Steam account level range attribute ID.", "level-05"),
        "real_hours": FieldMeta("Real hours played (for GameBoost).", 100),
        "skins_count": FieldMeta("Number of skins (for GameBoost).", 0),
        "steam_level": FieldMeta("Steam account level.", 10),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
