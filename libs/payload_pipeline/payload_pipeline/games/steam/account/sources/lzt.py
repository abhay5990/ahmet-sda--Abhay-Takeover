"""Parse prepared LZT payloads for the Steam slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class SteamLztSource:
    """Normalized Steam fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    steam_id: str = ""
    country: str = ""
    register_date: int = 0
    steam_level: int = 0
    total_games: int = 0
    games: list[dict[str, Any]] = field(default_factory=list)
    is_limited: bool = False
    cs2_rank_id: int = 0
    cs2_profile_rank: int = 0
    cs2_win_count: int = 0
    market_ban_end_date: int = 0
    dota2_mmr: int = 0
    dota2_win_count: int = 0
    dota2_lose_count: int = 0
    rust_kills: int = 0
    rust_deaths: int = 0


class SteamLztSourceAdapter:
    """Extract Steam data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> SteamLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        games: list[dict[str, Any]] = []
        full_games = payload.get("steam_full_games")
        if isinstance(full_games, dict):
            games_list = full_games.get("list")
            if isinstance(games_list, dict):
                games = [v for v in games_list.values() if isinstance(v, dict)]
            elif isinstance(games_list, list):
                games = [g for g in games_list if isinstance(g, dict)]

        return SteamLztSource(
            item_id=str(payload.get("item_id") or payload.get("steam_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            steam_id=str(payload.get("steam_id") or "").strip(),
            country=str(payload.get("steam_country") or "").strip().lower(),
            register_date=self._to_int(payload.get("steam_register_date"), default=0),
            steam_level=self._to_int(payload.get("steam_level"), default=0),
            total_games=len(games),
            games=games,
            is_limited=bool(self._to_int(payload.get("steam_is_limited"), default=0)),
            cs2_rank_id=self._to_int(payload.get("steam_cs2_rank_id"), default=0),
            cs2_profile_rank=self._to_int(payload.get("steam_cs2_profile_rank"), default=0),
            cs2_win_count=self._to_int(payload.get("steam_cs2_win_count"), default=0),
            market_ban_end_date=self._to_int(payload.get("steam_market_ban_end_date"), default=0),
            dota2_mmr=self._to_int(payload.get("steam_dota2_solo_mmr"), default=0),
            dota2_win_count=self._to_int(payload.get("steam_dota2_win_count"), default=0),
            dota2_lose_count=self._to_int(payload.get("steam_dota2_lose_count"), default=0),
            rust_kills=self._to_int(payload.get("steam_rust_kill_player"), default=0),
            rust_deaths=self._to_int(payload.get("steam_rust_deaths"), default=0),
        )

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
