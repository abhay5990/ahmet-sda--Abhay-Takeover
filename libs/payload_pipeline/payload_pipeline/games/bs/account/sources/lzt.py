"""Parse prepared LZT payloads for the Brawl Stars slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class BSLztSource:
    """Normalized Brawl Stars fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    level: int = 0
    trophies: int = 0
    brawler_count: int = 0
    legendary_brawler_count: int = 0
    max_level_brawlers_count: int = 0
    rank_30_plus_count: int = 0
    mythic_count: int = 0
    battle_pass_active: bool = False
    brawler_names: list[str] = field(default_factory=list)
    brawlers: dict[str, Any] = field(default_factory=dict)


class BSLztSourceAdapter:
    """Extract Brawl Stars data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> BSLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        brawlers_raw = payload.get("supercellBrawlers") or {}
        brawler_names, legendary_count, mythic_count = [], 0, 0
        max_level_count, rank_30_count = 0, 0

        if isinstance(brawlers_raw, dict):
            for brawler in brawlers_raw.values():
                if not isinstance(brawler, dict):
                    continue
                name = str(brawler.get("name", "")).strip()
                if name:
                    brawler_names.append(name)
                bclass = str(brawler.get("class", "")).lower()
                if bclass == "legendary":
                    legendary_count += 1
                elif bclass == "mythic":
                    mythic_count += 1
                power = self._to_int(brawler.get("power"), default=0)
                if power >= 11:
                    max_level_count += 1
                rank = self._to_int(brawler.get("rank"), default=0)
                if rank >= 30:
                    rank_30_count += 1

        return BSLztSource(
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
            level=self._to_int(payload.get("supercell_laser_level"), default=0),
            trophies=self._to_int(payload.get("supercell_laser_trophies"), default=0),
            brawler_count=self._to_int(payload.get("supercell_brawler_count"), default=len(brawler_names)),
            legendary_brawler_count=self._to_int(
                payload.get("supercell_legendary_brawler_count"), default=legendary_count
            ),
            max_level_brawlers_count=max_level_count,
            rank_30_plus_count=rank_30_count,
            mythic_count=mythic_count,
            battle_pass_active=bool(payload.get("supercell_laser_battle_pass")),
            brawler_names=brawler_names,
            brawlers=brawlers_raw if isinstance(brawlers_raw, dict) else {},
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
