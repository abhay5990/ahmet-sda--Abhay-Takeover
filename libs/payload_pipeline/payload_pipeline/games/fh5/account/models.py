"""Resolved models for the Forza Horizon 5 slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class Fh5ResolvedAccount(ResolvedAccountBase):
    """Single resolved Forza Horizon 5 account after source normalization."""

    platform: str = ""
    """Selected platform: PC, Xbox, or PS5."""

    edition: str = "Standard"
    """Game edition: Standard, Deluxe, or Premium."""

    cars_count: int = 0
    credits_count: int = 0

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "platform": FieldMeta("Account platform (PC / Xbox / PS5).", "PC"),
        "edition": FieldMeta("Game edition (Standard / Deluxe / Premium).", "Standard"),
        "cars_count": FieldMeta("Number of owned cars.", 50),
        "credits_count": FieldMeta("In-game credits.", 1000000),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
