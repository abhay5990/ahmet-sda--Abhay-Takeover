"""Parse prepared LZT payloads for the League of Legends slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class LolLztSource:
    """Normalized League of Legends fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    region: str = ""
    region_phrase: str = ""
    level: int = 0
    rank: str = ""
    rank_win_rate: float = 0.0
    champion_count: int = 0
    skin_count: int = 0
    blue_essence: int = 0
    orange_essence: int = 0
    mythic_essence: int = 0
    riot_points: int = 0
    champion_ids: list[int] = field(default_factory=list)
    skin_ids: list[int] = field(default_factory=list)


class LolLztSourceAdapter:
    """Extract League of Legends data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> LolLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        champion_ids, skin_ids = [], []
        inventory = payload.get("lolInventory")
        if isinstance(inventory, dict):
            champs = inventory.get("Champion") or inventory.get("Champions")
            if isinstance(champs, list):
                champion_ids = [int(c) for c in champs if self._safe_int(c) is not None]
            skins = inventory.get("Skin") or inventory.get("Skins")
            if isinstance(skins, list):
                skin_ids = [int(s) for s in skins if self._safe_int(s) is not None]

        return LolLztSource(
            item_id=str(payload.get("item_id") or payload.get("riot_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            region=str(payload.get("riot_lol_region") or "").strip(),
            region_phrase=str(payload.get("lolRegionPhrase") or "").strip(),
            level=self._to_int(payload.get("riot_lol_level"), default=0),
            rank=str(payload.get("riot_lol_rank") or "").strip(),
            rank_win_rate=self._to_float(payload.get("riot_lol_rank_win_rate"), default=0.0),
            champion_count=self._to_int(payload.get("riot_lol_champion_count"), default=len(champion_ids)),
            skin_count=self._to_int(payload.get("riot_lol_skin_count"), default=len(skin_ids)),
            blue_essence=self._to_int(payload.get("riot_lol_wallet_blue"), default=0),
            orange_essence=self._to_int(payload.get("riot_lol_wallet_orange"), default=0),
            mythic_essence=self._to_int(payload.get("riot_lol_wallet_mythic"), default=0),
            riot_points=self._to_int(payload.get("riot_lol_wallet_riot"), default=0),
            champion_ids=champion_ids,
            skin_ids=skin_ids,
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

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
