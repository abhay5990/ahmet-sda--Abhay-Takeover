"""Parse manual-entry payloads for the Valorant slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


_RANK_LABELS = {
    "unranked": "Unranked",
    "iron": "Iron",
    "bronze": "Bronze",
    "silver": "Silver",
    "gold": "Gold",
    "platinum": "Platinum",
    "diamond": "Diamond",
    "ascendant": "Ascendant",
    "immortal": "Immortal",
    "radiant": "Radiant",
}

_AGENT_RANGE_MIN = {
    "0-5-agents": 0,
    "6-10-agents": 6,
    "11-15-agents": 11,
    "16-20-agents": 16,
    "agents-2125": 21,
    "agents-26plus": 26,
}

_SKIN_RANGE_MIN = {
    "0-skins": 0,
    "1-9-skins": 1,
    "10-19-skins": 10,
    "20-39-skins": 20,
    "40-69-skins": 40,
    "70-99-skins": 70,
    "100-plus-skins": 100,
}

_KNIFE_RANGE_MIN = {
    "knives-0": 0,
    "knives-04": 1,
    "knives-59": 5,
    "knives-1014": 10,
    "knives-1519": 15,
    "knives-20plus": 20,
}

_SPENT_RANGE_MIN = {
    "spent-0499": 0,
    "spent-5999": 5000,
    "spent-101999": 10000,
    "spent-203499": 20000,
    "spent-35plus": 35000,
}


@dataclass(slots=True)
class ValorantManualSource:
    """Normalized Valorant fields from manual entry."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    title: str = ""
    description: str = ""
    images: str = ""

    region: str = ""
    level: int = 0
    current_rank: str = "Unranked"
    peak_rank: str = "No Rank"
    valorant_points: int = 0
    radianite_points: int = 0
    agent_count: int = 0
    skin_count: int = 0
    knife_count: int = 0
    inventory_value: int = 0
    account_tags: list[str] = field(default_factory=list)


class ValorantManualSourceAdapter:
    """Extract Valorant data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> ValorantManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        # New manual_fields dict takes priority, then legacy offer_details,
        # then top-level keys as fallback.
        mf = payload.get("manual_fields") if isinstance(payload.get("manual_fields"), dict) else {}
        offer_details = payload.get("offer_details") if isinstance(payload.get("offer_details"), dict) else {}

        def _value(key: str, default: Any = None) -> Any:
            for source in (mf, offer_details, payload):
                if key in source and source.get(key) not in (None, ""):
                    return source.get(key)
            return default

        def _str(key: str, default: str = "") -> str:
            return str(_value(key, default) or "").strip()

        price = self._to_float(payload.get("price"), default=0.0)

        return ValorantManualSource(
            item_id=str(payload.get("item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=price,
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            images=str(payload.get("images") or "").strip(),
            region=_str("region"),
            level=self._to_int(_value("level"), 0),
            current_rank=self._normalize_rank(_value("current_rank"), "Unranked"),
            peak_rank=self._normalize_rank(_value("peak_rank"), "No Rank"),
            valorant_points=self._to_int(_value("valorant_points"), 0),
            radianite_points=self._to_int(_value("radianite_points"), 0),
            agent_count=self._to_count(_value("agent_count"), _value("agents"), _AGENT_RANGE_MIN),
            skin_count=self._to_count(_value("weapon_skin_count"), _value("weapon_skins"), _SKIN_RANGE_MIN),
            knife_count=self._to_count(_value("knife_count"), _value("knives"), _KNIFE_RANGE_MIN),
            inventory_value=self._to_count(_value("inventory_value"), _value("spent_points"), _SPENT_RANGE_MIN),
            account_tags=self._to_list(_value("account_tags")),
        )

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_count(
        self,
        direct_value: Any,
        legacy_range: Any,
        range_map: dict[str, int],
    ) -> int:
        direct = self._to_int(direct_value, -1)
        if direct >= 0:
            return direct
        return range_map.get(str(legacy_range or "").strip(), 0)

    def _normalize_rank(self, value: Any, default: str) -> str:
        text = str(value or "").strip()
        if not text:
            return default
        slug = text.lower().replace("_", "-")
        return _RANK_LABELS.get(slug, text.title())

    def _to_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return []
