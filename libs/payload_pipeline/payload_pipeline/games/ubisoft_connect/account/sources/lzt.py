"""Parse prepared LZT payloads for the Ubisoft Connect slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class UbisoftLztSource:
    """Normalized Ubisoft Connect fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    uplay_id: str = ""
    country: str = ""
    created_date: int = 0
    game_count: int = 0
    games: dict[str, Any] = field(default_factory=dict)
    has_subscription: bool = False
    subscription_end_date: int = 0
    xbox_connected: bool = False
    psn_connected: bool = False
    balance: str = ""
    converted_balance: float = 0.0
    r6_level: int = 0
    r6_ban: bool = False


class UbisoftLztSourceAdapter:
    """Extract Ubisoft Connect data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> UbisoftLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        games = payload.get("uplay_games")
        if not isinstance(games, dict):
            games = {}

        game_count = self._to_int(payload.get("uplay_game_count"), default=0)
        if not game_count and games:
            game_count = len(games)

        return UbisoftLztSource(
            item_id=str(payload.get("item_id") or payload.get("uplay_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            uplay_id=str(payload.get("uplay_id") or "").strip(),
            country=str(payload.get("uplay_country") or "").strip().lower(),
            created_date=self._to_int(payload.get("uplay_created_date"), default=0),
            game_count=game_count,
            games=games,
            has_subscription=bool(payload.get("uplay_subscription")),
            subscription_end_date=self._to_int(payload.get("uplay_subscription_end_date"), default=0),
            xbox_connected=bool(payload.get("uplay_xbox_connected")),
            psn_connected=bool(payload.get("uplay_psn_connected")),
            balance=str(payload.get("uplay_balance") or "").strip(),
            converted_balance=self._to_float(payload.get("uplay_converted_balance"), default=0.0),
            r6_level=self._to_int(payload.get("uplay_r6_level"), default=0),
            r6_ban=bool(payload.get("uplay_r6_ban")),
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
