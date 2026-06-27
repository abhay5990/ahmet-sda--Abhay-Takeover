"""Parse manual-entry payloads for the Roblox slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class RobloxManualSource:
    """Normalized Roblox fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    title: str = ""
    description: str = ""

    # Eldorado attribute select IDs
    account_type: str = "other"
    game: str = "other"
    age_verified: str = "other"

    # Integer counts (manual entry)
    inventory_value: int = 0
    offsale_items: int = 0
    robux_value: int = 0


class RobloxManualSourceAdapter:
    """Extract Roblox data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> RobloxManualSource | None:
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

        return RobloxManualSource(
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
            game=_val("game"),
            inventory_value=_int_val("inventory_value"),
            offsale_items=_int_val("offsale_items"),
            robux_value=_int_val("robux_value"),
            age_verified=_val("age_verified"),
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
