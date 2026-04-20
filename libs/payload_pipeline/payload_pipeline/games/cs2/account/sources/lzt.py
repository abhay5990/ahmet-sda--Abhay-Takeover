"""Parse prepared LZT payloads for the CS2 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class CS2LztSource:
    """Minimal normalized CS2 fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    rank: str = ""
    rank_id: int = 0
    premier_elo: int = 0
    medals: list[str] = field(default_factory=list)
    is_prime: bool = False
    hours_played: int = 0
    games: list[dict[str, Any]] = field(default_factory=list)


class CS2LztSourceAdapter:
    """Extract CS2 data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CS2LztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        medals = payload.get("medals")
        if not isinstance(medals, list):
            medals = []

        games: list[dict[str, Any]] = []
        full_games = payload.get("steam_full_games")
        if isinstance(full_games, dict):
            games_list = full_games.get("list")
            if isinstance(games_list, dict):
                games = [v for v in games_list.values() if isinstance(v, dict)]
            elif isinstance(games_list, list):
                games = [g for g in games_list if isinstance(g, dict)]

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
            rank=str(payload.get("rank") or "").strip(),
            rank_id=self._to_int(payload.get("steam_cs2_rank_id"), default=0),
            premier_elo=self._to_int(
                payload.get("premier_elo", payload.get("premier_rating")),
                default=0,
            ),
            medals=[str(medal).strip() for medal in medals if str(medal).strip()],
            is_prime=bool(payload.get("is_prime")),
            hours_played=self._to_int(payload.get("hours_played"), default=0),
            games=games,
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
