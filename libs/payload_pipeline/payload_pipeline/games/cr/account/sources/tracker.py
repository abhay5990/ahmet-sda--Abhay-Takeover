"""Parse prepared tracker payloads for the Clash Royale slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class CrTrackerSource:
    """Normalized Clash Royale fields extracted from tracker payloads."""

    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    arena: int = 0
    cards_found: int = 0
    best_season_trophies: int = 0
    best_season_highest_trophies: int = 0
    best_season_id: str = ""
    path_of_legend_league: int = 0
    path_of_legend_trophies: int = 0
    games: int = 0
    losses: int = 0
    total_wins: int = 0
    total_losses: int = 0
    card_ids: list[int] = field(default_factory=list)
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)


class CrTrackerSourceAdapter:
    """Extract Clash Royale data from a prepared tracker source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CrTrackerSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        login_data = (
            raw_data.get("loginData")
            if isinstance(raw_data.get("loginData"), dict)
            else {}
        )
        email_data = (
            raw_data.get("emailLoginData")
            if isinstance(raw_data.get("emailLoginData"), dict)
            else {}
        )

        profile = raw_data.get("profile")
        if not isinstance(profile, dict):
            profile = raw_data

        card_stats = profile.get("cardStats")
        card_ids: list[int] = []
        total_wins, total_losses = 0, 0
        if isinstance(card_stats, dict):
            for card_id, stats in card_stats.items():
                safe_id = self._safe_int(card_id)
                if safe_id is not None:
                    card_ids.append(safe_id)
                if isinstance(stats, dict):
                    total_wins += self._to_int(stats.get("wins"), default=0)
                    total_losses += self._to_int(stats.get("losses"), default=0)

        path_of_legend = profile.get("bestPathOfLegendSeasonResult")
        pol_league, pol_trophies = 0, 0
        if isinstance(path_of_legend, dict):
            pol_league = self._to_int(path_of_legend.get("leagueNumber"), default=0)
            pol_trophies = self._to_int(path_of_legend.get("trophies"), default=0)

        cards = profile.get("cards")
        if not isinstance(cards, dict):
            cards = {}

        return CrTrackerSource(
            credentials=CredentialBundle(
                login=str(login_data.get("login") or raw_data.get("login") or "").strip(),
                password=str(login_data.get("password") or raw_data.get("password") or "").strip(),
                email_login=str(email_data.get("login") or raw_data.get("emailLogin") or "").strip(),
                email_password=str(email_data.get("password") or raw_data.get("emailPassword") or "").strip(),
            ),
            arena=self._to_int(profile.get("arena"), default=0),
            cards_found=self._to_int(profile.get("cardsFound"), default=0),
            best_season_trophies=self._to_int(profile.get("bestSeasonTrophies"), default=0),
            best_season_highest_trophies=self._to_int(
                profile.get("bestSeasonHighestTrophies"), default=0
            ),
            best_season_id=str(profile.get("bestSeasonId") or "").strip(),
            path_of_legend_league=pol_league,
            path_of_legend_trophies=pol_trophies,
            games=self._to_int(profile.get("games"), default=0),
            losses=self._to_int(profile.get("losses"), default=0),
            total_wins=total_wins,
            total_losses=total_losses,
            card_ids=card_ids,
            cards=cards,
        )

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default
