"""Parse prepared LZT payloads for the CS2 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class CS2LztSource:
    """Normalized CS2 fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    # Core CS2 stats
    rank_id: int = 0
    wingman_rank_id: int = 0
    premier_elo: int = 0
    is_prime: bool = False
    cs2_hours: int = 0
    profile_rank: int = 0

    # Medals
    medal_names: list[str] = field(default_factory=list)
    medal_count: int = 0

    # Steam profile
    steam_level: int = 0
    country: str = ""
    has_faceit: bool = False

    # Bans
    has_vac_ban: bool = False
    market_banned: bool = False

    # Games
    game_count: int = 0
    game_titles: list[str] = field(default_factory=list)
    games: list[dict[str, Any]] = field(default_factory=list)


class CS2LztSourceAdapter:
    """Extract CS2 data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CS2LztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        # --- Prime detection from game 730 title ---
        is_prime, cs2_hours = self._extract_cs2_game_info(payload)

        # --- Medals from steamCs2Medals ---
        medal_names, medal_count = self._extract_medals(payload)

        # --- Games list ---
        games, game_titles = self._extract_games(payload)
        game_count = self._to_int(payload.get("steam_game_count"), default=len(games))

        return CS2LztSource(
            item_id=str(payload.get("item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            rank_id=self._to_int(payload.get("steam_cs2_rank_id"), default=0),
            wingman_rank_id=self._to_int(payload.get("steam_cs2_wingman_rank_id"), default=0),
            premier_elo=self._to_int(payload.get("steam_cs2_premier_elo"), default=0),
            is_prime=is_prime,
            cs2_hours=cs2_hours,
            profile_rank=self._to_int(payload.get("steam_cs2_profile_rank"), default=0),
            medal_names=medal_names,
            medal_count=medal_count,
            steam_level=self._to_int(payload.get("steam_level"), default=0),
            country=str(payload.get("steam_country") or "").strip(),
            has_faceit=bool(payload.get("steam_has_faceit")),
            has_vac_ban=bool(payload.get("steam_cs2_ban_type")),
            market_banned=self._to_int(payload.get("steam_market"), default=1) == 0,
            game_count=game_count,
            game_titles=game_titles,
            games=games,
        )

    def _extract_cs2_game_info(self, payload: dict) -> tuple[bool, int]:
        """Detect prime status and hours from steam_full_games.list.730."""
        full_games = payload.get("steam_full_games")
        if not isinstance(full_games, dict):
            return bool(payload.get("is_prime")), 0

        games_list = full_games.get("list")
        cs2_game: dict = {}

        if isinstance(games_list, dict):
            cs2_game = games_list.get("730", games_list.get(730, {}))
        elif isinstance(games_list, list):
            for g in games_list:
                if isinstance(g, dict) and g.get("appid") == 730:
                    cs2_game = g
                    break

        if not cs2_game:
            return bool(payload.get("is_prime")), 0

        title = str(cs2_game.get("title") or "")
        is_prime = "prime" in title.lower()
        hours = int(self._to_float(cs2_game.get("playtime_forever"), default=0.0))
        return is_prime, hours

    def _extract_medals(self, payload: dict) -> tuple[list[str], int]:
        """Extract medal names from steamCs2Medals array."""
        raw_medals = payload.get("steamCs2Medals")
        if not isinstance(raw_medals, list) or not raw_medals:
            # Fallback to numeric count
            count = self._to_int(payload.get("steam_cs2_medal_count"), default=0)
            return [], count

        names: list[str] = []
        for m in raw_medals:
            if isinstance(m, dict):
                name = m.get("title") or m.get("name") or ""
            elif isinstance(m, str):
                name = m
            else:
                continue
            name = str(name).strip()
            if name:
                names.append(name)

        return names, len(raw_medals)

    def _extract_games(self, payload: dict) -> tuple[list[dict], list[str]]:
        """Extract games list and titles sorted by playtime."""
        full_games = payload.get("steam_full_games")
        if not isinstance(full_games, dict):
            return [], []

        games_list = full_games.get("list")
        games: list[dict] = []

        if isinstance(games_list, dict):
            games = [v for v in games_list.values() if isinstance(v, dict)]
        elif isinstance(games_list, list):
            games = [g for g in games_list if isinstance(g, dict)]

        # Sort by playtime descending
        games.sort(key=lambda g: g.get("playtime_forever", 0), reverse=True)
        titles = [g.get("title", "") for g in games if g.get("title")]

        return games, titles

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
