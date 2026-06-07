"""Parse prepared LZT payloads for the Clash Royale slice."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class CrLztSource:
    """Normalized Clash Royale fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    account_level: int = 0
    king_level: int = 0
    trophies: int = 0
    peak_trophies: int = 0
    arena: str = ""
    total_wins: int = 0
    cards_found: int = 0
    creation_year: int = 0
    battle_pass_active: bool = False
    player_tag: str = ""
    brawl_stars_level: int = 0
    brawl_stars_trophies: int = 0
    coc_th_level: int = 0
    coc_trophies: int = 0
    brawl_stars_tag: str = ""
    coc_tag: str = ""
    evolved_count: int = 0


class CrLztSourceAdapter:
    """Extract Clash Royale data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CrLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        player_tag = ""
        brawl_stars_tag = ""
        coc_tag = ""
        systems_raw = payload.get("supercell_systems")
        if isinstance(systems_raw, str):
            try:
                systems = json.loads(systems_raw)
                player_tag = str(systems.get("scroll", "")).strip()
                brawl_stars_tag = str(systems.get("laser", "")).strip()
                coc_tag = str(systems.get("magic", "")).strip()
            except (json.JSONDecodeError, AttributeError):
                pass
        elif isinstance(systems_raw, dict):
            player_tag = str(systems_raw.get("scroll", "")).strip()
            brawl_stars_tag = str(systems_raw.get("laser", "")).strip()
            coc_tag = str(systems_raw.get("magic", "")).strip()

        return CrLztSource(
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
            account_level=self._to_int(payload.get("supercell_scroll_level"), default=0),
            king_level=self._to_int(payload.get("supercell_king_level"), default=0),
            trophies=self._to_int(payload.get("supercell_scroll_trophies"), default=0),
            peak_trophies=0,
            arena=str(payload.get("supercell_arena") or "").strip(),
            total_wins=self._to_int(payload.get("supercell_scroll_victories"), default=0),
            cards_found=0,
            creation_year=self._to_int(payload.get("supercell_creation_year"), default=0),
            battle_pass_active=bool(payload.get("supercell_scroll_battle_pass")),
            player_tag=player_tag,
            brawl_stars_level=self._to_int(payload.get("supercell_laser_level"), default=0),
            brawl_stars_trophies=self._to_int(payload.get("supercell_laser_trophies"), default=0),
            coc_th_level=self._to_int(payload.get("supercell_town_hall_level"), default=0),
            coc_trophies=self._to_int(payload.get("supercell_magic_trophies"), default=0),
            brawl_stars_tag=brawl_stars_tag,
            coc_tag=coc_tag,
            evolved_count=self._to_int(payload.get("supercell_scroll_evolved_count"), default=0),
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
