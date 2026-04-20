"""Parse prepared LZT payloads for the Valorant account slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..catalog import load_default_catalog
from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class ValorantLztSource:
    """Normalized Valorant fields extracted from a prepared LZT payload."""

    item_id: str = ""
    category_id: int = 13
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    tracker_url: str = ""
    region: str = ""
    level: int = 0
    valorant_points: int = 0
    radianite_points: int = 0
    rank_type: str = ""
    current_rank: str = "Unranked"
    previous_rank: str = "No Rank"
    last_rank: str = "No Rank"
    agent_names: list[str] = field(default_factory=list)
    skin_names: list[str] = field(default_factory=list)
    buddy_names: list[str] = field(default_factory=list)
    preview_urls: dict[str, str] = field(default_factory=dict)
    skin_count: int = 0
    agent_count: int = 0
    buddy_count: int = 0
    knife_count: int = 0
    inventory_value: int = 0


class ValorantLztSourceAdapter:
    """Extract Valorant account data from a prepared LZT envelope."""

    def __init__(self) -> None:
        self.catalog = load_default_catalog()

    def parse(self, raw_data: dict[str, Any] | None) -> ValorantLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}
        inventory = payload.get("valorantInventory") if isinstance(payload.get("valorantInventory"), dict) else {}

        skin_ids = self._extract_inventory_ids(inventory.get("WeaponSkins"))
        agent_ids = self._extract_inventory_ids(inventory.get("Agent"))
        buddy_ids = self._extract_inventory_ids(inventory.get("Buddy"))

        skin_names = self.catalog.resolve_skins(skin_ids)
        agent_names = self.catalog.resolve_agents(agent_ids)
        buddy_names = self.catalog.resolve_buddies(buddy_ids)

        return ValorantLztSource(
            item_id=str(payload.get("item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=13),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            tracker_url=self._resolve_tracker_url(payload),
            region=str(payload.get("riot_valorant_region") or "").strip().upper(),
            level=self._to_int(payload.get("riot_valorant_level"), default=0),
            valorant_points=self._to_int(payload.get("riot_valorant_wallet_vp"), default=0),
            radianite_points=self._to_int(payload.get("riot_valorant_wallet_rp"), default=0),
            rank_type=str(payload.get("riot_valorant_rank_type") or "").strip(),
            current_rank=str(payload.get("valorantRankTitle") or "Unranked").strip() or "Unranked",
            previous_rank=str(payload.get("valorantPreviousRankTitle") or "No Rank").strip() or "No Rank",
            last_rank=str(payload.get("valorantLastRankTitle") or "No Rank").strip() or "No Rank",
            agent_names=agent_names,
            skin_names=skin_names,
            buddy_names=buddy_names,
            preview_urls=self._resolve_preview_urls(payload),
            skin_count=self._resolve_count(payload.get("riot_valorant_skin_count"), fallback=len(skin_names)),
            agent_count=self._resolve_count(payload.get("riot_valorant_agent_count"), fallback=len(agent_names)),
            buddy_count=len(buddy_names),
            knife_count=self._to_int(payload.get("riot_valorant_knife_count"), default=0),
            inventory_value=self._to_int(payload.get("riot_valorant_inventory_value"), default=0),
        )

    def _resolve_tracker_url(self, payload: dict[str, Any]) -> str:
        direct = str(payload.get("tracker_link") or payload.get("accountLink") or "").strip()
        if direct:
            return direct

        links = payload.get("accountLinks")
        if not isinstance(links, list):
            return ""

        for record in links:
            if not isinstance(record, dict):
                continue
            label = str(record.get("text") or "").strip().lower()
            link = str(record.get("link") or "").strip()
            if "tracker" in label and link:
                return link
        return ""

    def _resolve_preview_urls(self, payload: dict[str, Any]) -> dict[str, str]:
        preview_links = payload.get("imagePreviewLinks")
        if not isinstance(preview_links, dict):
            return {}

        direct_links = preview_links.get("direct")
        if not isinstance(direct_links, dict):
            return {}

        mapping = {
            "weapons": str(direct_links.get("weapons") or "").strip(),
            "agents": str(direct_links.get("agents") or "").strip(),
            "buddies": str(direct_links.get("buddies") or "").strip(),
        }
        return {key: value for key, value in mapping.items() if value}

    def _extract_inventory_ids(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            candidates = value.values()
        elif isinstance(value, list):
            candidates = value
        else:
            candidates = []

        ids: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            item_id = str(candidate or "").strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            ids.append(item_id)
        return ids

    def _resolve_count(self, value: Any, *, fallback: int) -> int:
        count = self._to_int(value, default=0)
        if count > 0:
            return count
        return max(0, fallback)

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
