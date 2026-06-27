"""Parse manual-entry payloads for the Genshin Impact slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class GiManualSource:
    """Normalized Genshin Impact fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    title: str = ""
    description: str = ""

    # Eldorado attribute select IDs
    account_type: str = "other"

    # Integer counts (manual entry)
    adventure_rank: int = 0
    characters: int = 0
    events_count: int = 0
    legendary_weapons: int = 0
    primogems: int = 0

    # tradeEnvironments (Region)
    region: str = "other"


class GiManualSourceAdapter:
    """Extract Genshin Impact data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> GiManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}
        mf = payload.get("manual_fields") if isinstance(payload.get("manual_fields"), dict) else {}
        offer_details = payload.get("offer_details") or {}
        if not isinstance(offer_details, dict):
            offer_details = {}

        def _val(key: str, default: str = "other") -> str:
            for src in (mf, offer_details, payload):
                v = src.get(key)
                if v not in (None, ""):
                    return str(v).strip()
            return default

        def _int_val(key: str, default: int = 0) -> int:
            for src in (mf, offer_details, payload):
                v = src.get(key)
                if v not in (None, ""):
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        continue
            return default

        return GiManualSource(
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
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            account_type=_val("account_type"),
            adventure_rank=_int_val("adventure_rank"),
            characters=_int_val("characters"),
            events_count=_int_val("events_count"),
            legendary_weapons=_int_val("legendary_weapons"),
            primogems=_int_val("primogems"),
            region=_val("region"),
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
