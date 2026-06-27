"""GameBoost builder for resolved Valorant accounts."""

from __future__ import annotations

from typing import Any

from ..models import ValorantResolvedAccount
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id
from .....marketplaces.gameboost import BaseGameBoostBuilder

_UNRANKED_VALUES = {"Unranked", "Ranked Ready", "No rank", "No Rank", "Unrated", ""}
_SERVER_FALLBACKS = {
    "na": "North America",
    "eu": "Europe",
    "la": "Latin America",
    "latam": "Latin America",
    "br": "Brazil",
    "ap": "Asia Pacific",
    "apac": "Asia Pacific",
    "kr": "Asia Pacific",
    "tr": "Turkey",
}


class ValorantGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Valorant account slice."""

    @property
    def game_slug(self) -> str:
        return "valorant"

    @property
    def _platform_name(self) -> str:
        return "Riot Account"

    def _build_account_data(
        self, account: ValorantResolvedAccount, ctx: BuildContext | None = None,
    ) -> dict[str, Any]:
        server = get_external_id(
            ctx.variant_context if ctx else None, "region", account.region,
        ) or _SERVER_FALLBACKS.get(str(account.region or "").strip().lower()) or "Asia Pacific"
        return {
            "server": server,
            "current_tier": self._extract_rank(account.current_rank),
            "current_division": self._extract_division(account.current_rank),
            "peak_tier": self._extract_rank(account.last_rank),
            "peak_division": self._extract_division(account.last_rank),
            "platforms": ["PC"],
            "is_ranked_ready": account.level >= 20,
            "level": account.level,
            "valorant_points": account.valorant_points,
            "radianite_points": account.radianite_points,
        }

    def _build_dump(self, account: ValorantResolvedAccount) -> str | None:
        return self._generate_tags(account.skin_names)

    def _build_game_items(self, account: ValorantResolvedAccount) -> dict[str, Any] | None:
        return {
            "agents": list(account.agent_names),
            "weapon-skins": list(account.skin_names),
            "buddies": list(account.buddy_names),
            "cards": [],
            "sprays": [],
            "titles": [],
        }

    # ------------------------------------------------------------------
    # Game-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_rank(rank: str) -> str:
        if not rank or rank in _UNRANKED_VALUES:
            return "Unranked"
        return rank.split()[0]

    @staticmethod
    def _extract_division(rank: str) -> int:
        if not rank or rank in _UNRANKED_VALUES:
            return 1
        parts = rank.split()
        if len(parts) > 1:
            try:
                return int(parts[-1])
            except ValueError:
                return 1
        return 1

    @staticmethod
    def _generate_tags(skin_names: list[str]) -> str:
        """Build a comma-separated tag string from skin names (2000 char cap)."""
        def _convert(text: str) -> str:
            return text.translate(str.maketrans("\u0131\u0130", "ii"))

        tags: list[str] = []
        total = 0
        for name in skin_names:
            cleaned = _convert(str(name))
            length = len(cleaned) + (2 if tags else 0)
            if total + length > 2000:
                break
            tags.append(cleaned)
            total += length
        return ", ".join(tags)
