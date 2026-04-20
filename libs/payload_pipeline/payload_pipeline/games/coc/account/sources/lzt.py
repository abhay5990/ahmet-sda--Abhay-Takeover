"""Parse prepared LZT payloads for the Clash of Clans slice."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class CocLztSource:
    """Normalized Clash of Clans fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    town_hall_level: int = 0
    builder_hall_level: int = 0
    account_level: int = 0
    trophies: int = 0
    best_trophies: int = 0
    war_stars: int = 0
    barbarian_king_level: int = 0
    archer_queen_level: int = 0
    grand_warden_level: int = 0
    royal_champion_level: int = 0
    total_heroes_level: int = 0
    total_troops_level: int = 0
    total_spells_level: int = 0
    total_builder_heroes_level: int = 0
    total_builder_troops_level: int = 0
    creation_year: int = 0
    has_phone: bool = False
    battle_pass_active: bool = False
    player_tag: str = ""


class CocLztSourceAdapter:
    """Extract Clash of Clans data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CocLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        player_tag = ""
        systems_raw = payload.get("supercell_systems")
        if isinstance(systems_raw, str):
            try:
                systems = json.loads(systems_raw)
                player_tag = str(systems.get("magic", "")).strip()
            except (json.JSONDecodeError, AttributeError):
                pass
        elif isinstance(systems_raw, dict):
            player_tag = str(systems_raw.get("magic", "")).strip()

        return CocLztSource(
            item_id=str(payload.get("item_id") or payload.get("supercell_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            town_hall_level=self._to_int(payload.get("supercell_town_hall_level"), default=0),
            builder_hall_level=self._to_int(payload.get("supercell_builder_hall_level"), default=0),
            account_level=self._to_int(payload.get("supercell_magic_level"), default=0),
            trophies=self._to_int(payload.get("supercell_magic_trophies"), default=0),
            best_trophies=0,
            war_stars=0,
            barbarian_king_level=self._to_int(payload.get("supercell_king_level"), default=0),
            archer_queen_level=0,
            grand_warden_level=0,
            royal_champion_level=0,
            total_heroes_level=self._to_int(payload.get("supercell_total_heroes_level"), default=0),
            total_troops_level=self._to_int(payload.get("supercell_total_troops_level"), default=0),
            total_spells_level=self._to_int(payload.get("supercell_total_spells_level"), default=0),
            total_builder_heroes_level=self._to_int(payload.get("supercell_total_builder_heroes_level"), default=0),
            total_builder_troops_level=self._to_int(payload.get("supercell_total_builder_troops_level"), default=0),
            creation_year=self._to_int(payload.get("supercell_creation_year"), default=0),
            has_phone=bool(payload.get("supercell_phone")),
            battle_pass_active=bool(payload.get("supercell_magic_battle_pass")),
            player_tag=player_tag,
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
