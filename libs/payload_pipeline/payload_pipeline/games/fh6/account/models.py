"""Resolved models for the Forza Horizon 6 slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class Fh6ResolvedAccount(ResolvedAccountBase):
    """Single resolved Forza Horizon 6 account after source normalization."""

    platform: str = ""
    """Selected platform: PC, Xbox, or PS5."""

    credits_count: int = 0
    all_cars: str = "No"

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "platform": FieldMeta("Account platform (PC / Xbox / PS5).", "PC"),
        "credits_count": FieldMeta("In-game credits.", 1000000),
        "all_cars": FieldMeta("Whether all cars are unlocked.", "No"),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
