"""GameBoost builder for resolved R6 accounts."""

from __future__ import annotations

from typing import Any

from ..models import R6ResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder

_UNRANKED_VALUES = {"Unranked", "Ranked Ready", "No Rank", "No rank", ""}


class R6GameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the R6 account slice."""

    @property
    def game_slug(self) -> str:
        return "rainbow-six-siege"

    @property
    def _platform_name(self) -> str:
        return "Ubisoft Account"

    def _build_account_data(
        self, account: R6ResolvedAccount,
    ) -> dict[str, Any]:
        return {
            "platform": self._get_primary_platform(account),
            "linkable_platforms": account.available_platforms,
            "operators_count": account.operator_count,
            "current_level": account.level,
            "current_tier": self._extract_tier(account.current_rank),
            "current_division": self._extract_division(account.current_rank),
            "previous_tier": self._extract_tier(account.peak_rank),
            "previous_division": self._extract_division(account.peak_rank),
            "boosters_count": 0,
            "renown_count": account.renown,
            "credits_count": account.credits,
            "cosmetics_count": account.skin_count,
        }

    def _build_dump(self, account: R6ResolvedAccount) -> str | None:
        if not account.skin_names:
            return None
        return self._generate_tags(account.skin_names)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_primary_platform(account: R6ResolvedAccount) -> str:
        if account.psn_connected:
            return "PlayStation"
        if account.xbox_connected:
            return "Xbox"
        return "PC"

    @staticmethod
    def _extract_tier(rank: str) -> str:
        if not rank or rank in _UNRANKED_VALUES:
            return "Unranked"
        return rank.split()[0]

    @staticmethod
    def _extract_division(rank: str) -> str | None:
        if not rank or rank in _UNRANKED_VALUES:
            return None
        parts = rank.split()
        return parts[-1] if len(parts) > 1 else None

    @staticmethod
    def _generate_tags(skin_names: list[str]) -> str:
        """Build comma-separated tag string from skin names (2000 char cap)."""
        tags: list[str] = []
        total = 0
        for name in skin_names:
            length = len(name) + (2 if tags else 0)
            if total + length > 2000:
                break
            tags.append(name)
            total += length
        return ", ".join(tags)
