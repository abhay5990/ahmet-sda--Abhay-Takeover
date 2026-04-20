"""GameBoost builder for resolved League of Legends accounts."""

from __future__ import annotations

from typing import Any

from ..models import LolResolvedAccount
from .. import catalog
from .....marketplaces.gameboost import BaseGameBoostBuilder


# region_phrase -> GameBoost server name
_SERVER_MAP: dict[str, str] = {
    "Latin America North": "Latin America North",
    "Europe Nordic & East": "Europe Nordic & East",
    "Europe West": "Europe West",
    "Turkey": "Turkey",
    "North America": "North America",
    "Russia": "Russia",
    "Vietnam": "Vietnam",
    "Japan": "Japan",
    "Brazil": "Brazil",
    "Latin America South": "Latin America South",
    "Singapore, Malaysia & Indonesia": "Singapore",
    "Thailand": "Thailand",
    "Oceania": "Oceania",
    "Philippines": "Philippines",
}

_UNRANKED_VALUES = {"Unranked", "Ranked Ready", "Rank Ready", "No rank", "No Rank", "Unrated", ""}


class LolGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the League of Legends account slice."""

    @property
    def game_slug(self) -> str:
        return "league-of-legends"

    @property
    def _platform_name(self) -> str:
        return "Riot Account"

    def _build_account_data(self, account: LolResolvedAccount) -> dict[str, Any]:
        return {
            "server": _SERVER_MAP.get(account.region_phrase, "Public Beta Environment"),
            "level_up_method": "by_hand",
            "current_tier": self._extract_rank(account.rank),
            "current_division": self._extract_division(account.rank),
            "flex_tier": "Unranked",
            "flex_division": None,
            "is_ranked_ready": account.level >= 30,
            "level": str(account.level),
            "winrate": account.rank_win_rate if account.rank_win_rate > 0 else None,
            "blue_essence": account.blue_essence,
            "riot_points": account.riot_points,
        }

    def _build_dump(self, account: LolResolvedAccount) -> str | None:
        return self._generate_dump(account)

    def _build_game_items(self, account: LolResolvedAccount) -> dict[str, Any] | None:
        return {
            "champions": catalog.champion_titles(account.champion_ids),
            "skins": catalog.skin_titles(account.skin_ids),
            "roles": ["Top", "Mid", "Jungle"],
        }

    # ------------------------------------------------------------------
    # Game-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_rank(rank: str) -> str:
        if not rank or rank in _UNRANKED_VALUES:
            return "Unranked"
        rank_lower = rank.lower()
        for tier in ("Challenger", "Grandmaster", "Master", "Diamond", "Emerald",
                     "Platinum", "Gold", "Silver", "Bronze", "Iron"):
            if tier.lower() in rank_lower:
                return tier
        return rank.split()[0] if rank.split() else "Unranked"

    @staticmethod
    def _extract_division(rank: str) -> str | None:
        if not rank or rank in _UNRANKED_VALUES:
            return None
        words = rank.split()
        if len(words) > 1:
            last = words[-1]
            if last in ("IV", "III", "II", "I", "4", "3", "2", "1"):
                return last
        return None

    @staticmethod
    def _generate_dump(account: LolResolvedAccount) -> str:
        """Build a dump string with champion and skin titles for search/SEO.

        Truncated to ~2000 chars to stay within GameBoost field limits.
        """
        champ_titles = catalog.champion_titles(account.champion_ids)
        skin_titles = catalog.skin_titles(account.skin_ids)

        parts: list[str] = []
        if champ_titles:
            parts.append("Champions: " + ", ".join(champ_titles))
        if skin_titles:
            parts.append("Skins: " + ", ".join(skin_titles))
        if not parts:
            return "Handmade"

        dump = " | ".join(parts)
        if len(dump) > 2000:
            dump = dump[:1997] + "..."
        return dump
