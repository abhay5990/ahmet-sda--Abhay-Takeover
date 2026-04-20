"""Parse prepared tracker payloads for the Clash of Clans slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle

# Hero ID mapping from CoC API
_HERO_ID_MAP = {
    0: "barbarian_king",
    1: "archer_queen",
    2: "grand_warden",
    3: "royal_champion",
    4: "royal_champion",  # alternate ID
}


@dataclass(slots=True)
class CocTrackerSource:
    """Normalized Clash of Clans fields extracted from tracker payloads."""

    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    player_tag: str = ""
    name: str = ""
    town_hall_level: int = 0
    town_hall_weapon_level: int = 0
    builder_hall_level: int = 0
    account_level: int = 0
    trophies: int = 0
    best_trophies: int = 0
    war_stars: int = 0
    attack_wins: int = 0
    defense_wins: int = 0
    donations: int = 0
    donations_received: int = 0

    barbarian_king_level: int = 0
    archer_queen_level: int = 0
    grand_warden_level: int = 0
    royal_champion_level: int = 0

    heroes: list[dict[str, Any]] = field(default_factory=list)
    troops: list[dict[str, Any]] = field(default_factory=list)
    spells: list[dict[str, Any]] = field(default_factory=list)
    hero_equipment: list[dict[str, Any]] = field(default_factory=list)
    super_troops: list[dict[str, Any]] = field(default_factory=list)

    achievements: list[dict[str, Any]] = field(default_factory=list)


class CocTrackerSourceAdapter:
    """Extract Clash of Clans data from a prepared tracker source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CocTrackerSource | None:
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

        heroes = self._parse_heroes(raw_data.get("heroes"))

        return CocTrackerSource(
            credentials=CredentialBundle(
                login=str(login_data.get("login") or raw_data.get("login") or "").strip(),
                password=str(login_data.get("password") or raw_data.get("password") or "").strip(),
                email_login=str(email_data.get("login") or raw_data.get("emailLogin") or "").strip(),
                email_password=str(email_data.get("password") or raw_data.get("emailPassword") or "").strip(),
            ),
            player_tag=str(raw_data.get("tag") or "").strip(),
            name=str(raw_data.get("name") or "").strip(),
            town_hall_level=self._to_int(raw_data.get("townHallLevel"), default=0),
            town_hall_weapon_level=self._to_int(raw_data.get("townHallWeaponLevel"), default=0),
            builder_hall_level=self._to_int(raw_data.get("builderHallLevel"), default=0),
            account_level=self._to_int(raw_data.get("expLevel"), default=0),
            trophies=self._to_int(raw_data.get("trophies"), default=0),
            best_trophies=self._to_int(raw_data.get("bestTrophies"), default=0),
            war_stars=self._to_int(raw_data.get("warStars"), default=0),
            attack_wins=self._to_int(raw_data.get("attackWins"), default=0),
            defense_wins=self._to_int(raw_data.get("defenseWins"), default=0),
            donations=self._to_int(raw_data.get("donations"), default=0),
            donations_received=self._to_int(raw_data.get("donationsReceived"), default=0),
            barbarian_king_level=heroes.get("barbarian_king", 0),
            archer_queen_level=heroes.get("archer_queen", 0),
            grand_warden_level=heroes.get("grand_warden", 0),
            royal_champion_level=heroes.get("royal_champion", 0),
            heroes=self._parse_dict_list(raw_data.get("heroes")),
            troops=self._parse_dict_list(raw_data.get("troops")),
            spells=self._parse_dict_list(raw_data.get("spells")),
            hero_equipment=self._parse_dict_list(raw_data.get("heroEquipment")),
            super_troops=self._parse_dict_list(raw_data.get("superTroops")),
            achievements=self._parse_achievements(raw_data.get("achievements")),
        )

    def _parse_heroes(self, raw_heroes: Any) -> dict[str, int]:
        """Parse hero levels from tracker heroes array."""
        result: dict[str, int] = {}
        if not isinstance(raw_heroes, list):
            return result

        for hero in raw_heroes:
            if not isinstance(hero, dict):
                continue
            hero_id = self._to_int(hero.get("id"), default=-1)
            level = self._to_int(hero.get("level"), default=0)
            hero_name = _HERO_ID_MAP.get(hero_id)
            if hero_name and level > result.get(hero_name, 0):
                result[hero_name] = level

        return result

    def _parse_dict_list(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _parse_achievements(self, raw_achievements: Any) -> list[dict[str, Any]]:
        return self._parse_dict_list(raw_achievements)

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default
