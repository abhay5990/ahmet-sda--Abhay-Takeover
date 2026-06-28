"""Parse prepared LZT payloads for the Genshin Impact slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle
from ..models import GenshinCharacter, HonkaiCharacter, ZenlessCharacter


@dataclass(slots=True)
class GenshinLztSource:
    """Normalized miHoYo fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    region: str = ""

    genshin_level: int = 0
    genshin_character_count: int = 0
    genshin_legendary_characters: int = 0
    genshin_constellations: int = 0
    genshin_legendary_weapons: int = 0
    genshin_achievement_count: int = 0
    genshin_abyss_progress: str = ""
    genshin_activity_days: int = 0
    genshin_currency: int = 0

    honkai_level: int = 0
    honkai_character_count: int = 0
    honkai_legendary_characters: int = 0
    honkai_eidolons: int = 0
    honkai_legendary_weapons: int = 0
    honkai_achievement_count: int = 0
    honkai_abyss_progress: str = ""
    honkai_activity_days: int = 0
    honkai_currency: int = 0

    zenless_level: int = 0
    zenless_character_count: int = 0
    zenless_legendary_characters: int = 0
    zenless_cinemas: int = 0
    zenless_achievement_count: int = 0
    zenless_abyss_progress: str = ""

    # Character detail lists
    genshin_characters: list[GenshinCharacter] = field(default_factory=list)
    honkai_characters: list[HonkaiCharacter] = field(default_factory=list)
    zenless_characters: list[ZenlessCharacter] = field(default_factory=list)


class GenshinLztSourceAdapter:
    """Extract miHoYo data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> GenshinLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        return GenshinLztSource(
            item_id=str(payload.get("item_id") or payload.get("mihoyo_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            region=str(payload.get("mihoyo_region") or "").strip(),
            genshin_level=self._to_int(payload.get("mihoyo_genshin_level"), default=0),
            genshin_character_count=self._to_int(payload.get("mihoyo_genshin_character_count"), default=0),
            genshin_legendary_characters=self._to_int(payload.get("mihoyo_genshin_legendary_characters_count"), default=0),
            genshin_constellations=self._to_int(payload.get("mihoyo_genshin_constellations_count"), default=0),
            genshin_legendary_weapons=self._to_int(payload.get("mihoyo_genshin_legendary_weapons_count"), default=0),
            genshin_achievement_count=self._to_int(payload.get("mihoyo_genshin_achievement_count"), default=0),
            genshin_abyss_progress=str(payload.get("mihoyo_genshin_abyss_process") or "").strip(),
            genshin_activity_days=self._to_int(payload.get("mihoyo_genshin_activity_days"), default=0),
            genshin_currency=self._to_int(payload.get("mihoyo_genshin_currency"), default=0),
            honkai_level=self._to_int(payload.get("mihoyo_honkai_level"), default=0),
            honkai_character_count=self._to_int(payload.get("mihoyo_honkai_character_count"), default=0),
            honkai_legendary_characters=self._to_int(payload.get("mihoyo_honkai_legendary_characters_count"), default=0),
            honkai_eidolons=self._to_int(payload.get("mihoyo_honkai_eidolons_count"), default=0),
            honkai_legendary_weapons=self._to_int(payload.get("mihoyo_honkai_legendary_weapons_count"), default=0),
            honkai_achievement_count=self._to_int(payload.get("mihoyo_honkai_achievement_count"), default=0),
            honkai_abyss_progress=str(payload.get("mihoyo_honkai_abyss_process") or "").strip(),
            honkai_activity_days=self._to_int(payload.get("mihoyo_honkai_activity_days"), default=0),
            honkai_currency=self._to_int(payload.get("mihoyo_honkai_currency"), default=0),
            zenless_level=self._to_int(payload.get("mihoyo_zenless_level"), default=0),
            zenless_character_count=self._to_int(payload.get("mihoyo_zenless_character_count"), default=0),
            zenless_legendary_characters=self._to_int(payload.get("mihoyo_zenless_legendary_characters_count"), default=0),
            zenless_cinemas=self._to_int(payload.get("mihoyo_zenless_cinemas_count"), default=0),
            zenless_achievement_count=self._to_int(payload.get("mihoyo_zenless_achievement_count"), default=0),
            zenless_abyss_progress=str(payload.get("mihoyo_zenless_abyss_process") or "").strip(),
            genshin_characters=self._parse_genshin_characters(payload.get("genshinCharacters")),
            honkai_characters=self._parse_honkai_characters(payload.get("honkaiCharacters")),
            zenless_characters=self._parse_zenless_characters(payload.get("zenlessCharacters")),
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

    def _parse_genshin_characters(self, raw: Any) -> list[GenshinCharacter]:
        if not isinstance(raw, list):
            return []
        result: list[GenshinCharacter] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            weapon = entry.get("weapon") or {}
            if not isinstance(weapon, dict):
                weapon = {}
            result.append(GenshinCharacter(
                name=name,
                rarity=self._to_int(entry.get("rarity"), default=4),
                element=str(entry.get("element") or "").strip(),
                level=self._to_int(entry.get("level"), default=0),
                constellation=self._to_int(entry.get("actived_constellation_num"), default=0),
                weapon_name=str(weapon.get("name") or "").strip(),
                weapon_rarity=self._to_int(weapon.get("rarity"), default=0),
            ))
        return result

    def _parse_honkai_characters(self, raw: Any) -> list[HonkaiCharacter]:
        if not isinstance(raw, list):
            return []
        result: list[HonkaiCharacter] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            equip = entry.get("equip") or {}
            if not isinstance(equip, dict):
                equip = {}
            result.append(HonkaiCharacter(
                name=name,
                rarity=self._to_int(entry.get("rarity"), default=4),
                element=str(entry.get("element") or "").strip(),
                level=self._to_int(entry.get("level"), default=0),
                eidolon=self._to_int(entry.get("rank"), default=0),
                weapon_name=str(equip.get("name") or "").strip(),
                weapon_rarity=self._to_int(equip.get("rarity"), default=0),
            ))
        return result

    def _parse_zenless_characters(self, raw: Any) -> list[ZenlessCharacter]:
        if not isinstance(raw, list):
            return []
        result: list[ZenlessCharacter] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            result.append(ZenlessCharacter(
                name=name,
                rarity=self._to_int(entry.get("rarity"), default=4),
                element=str(entry.get("element") or "").strip(),
                level=self._to_int(entry.get("level"), default=0),
                cinema=self._to_int(entry.get("rank") or entry.get("cinema"), default=0),
            ))
        return result
