"""Resolved models for the CS2 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class CS2ResolvedAccount(ResolvedAccountBase):
    """Single resolved account used after source normalization."""

    rank: str = ""
    rank_id: int = 0
    premier_elo: int = 0
    medals: list[str] = field(default_factory=list)
    is_prime: bool = False
    has_email_access: bool = False
    hours_played: int = 0
    games: list[dict[str, Any]] = field(default_factory=list)

    # Manual numeric override for medal count (when no medals list available)
    medal_count_manual: int = 0

    # Attribute slug overrides (from manual entry — Eldorado select IDs)
    prime_attr: str = ""
    veteran_coin_attr: str = ""
    esea_attr: str = ""
    faceit_attr: str = ""

    @property
    def medal_count(self) -> int:
        if self.medals:
            return len(self.medals)
        return self.medal_count_manual

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "rank": FieldMeta("Competitive rank name.", "Gold Nova Master"),
        "rank_id": FieldMeta("Numeric rank ID.", 12),
        "premier_elo": FieldMeta("Premier mode ELO rating.", 14500),
        "medals": FieldMeta("Service medal names.", ["2023 Service Medal", "Global Offensive Medal"]),
        "is_prime": FieldMeta("Prime status.", True),
        "has_email_access": FieldMeta("Email access status.", True),
        "hours_played": FieldMeta("Total hours played.", 1200),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "medal_count": FieldMeta("Number of service medals.", 2, "computed"),
    }
