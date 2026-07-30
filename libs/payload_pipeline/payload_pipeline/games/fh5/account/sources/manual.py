"""Parse manual-entry payloads for the Forza Horizon 5 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class Fh5ManualSource:
    """Normalized Forza Horizon 5 fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    title: str = ""
    description: str = ""

    platform: str = ""
    edition: str = "Standard"
    cars_count: int = 0
    credits_count: int = 0


class Fh5ManualSourceAdapter:
    """Extract Forza Horizon 5 data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> Fh5ManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}
        offer_details = payload.get("offer_details") or {}
        if not isinstance(offer_details, dict):
            offer_details = {}
        # The stock-start UI submits values under ``manual_fields``; older/dropship
        # payloads use ``offer_details`` or top-level keys. Read all three so the
        # selected platform actually drives the Eldorado trade environment.
        manual_fields = payload.get("manual_fields") or {}
        if not isinstance(manual_fields, dict):
            manual_fields = {}

        def _val(key: str, default: str = "") -> str:
            for src in (manual_fields, offer_details, payload):
                v = src.get(key)
                if v not in (None, ""):
                    return str(v).strip()
            return default

        def _int(key: str, default: int = 0) -> int:
            for src in (manual_fields, offer_details, payload):
                if src.get(key) not in (None, ""):
                    return self._to_int(src.get(key), default=default)
            return default

        return Fh5ManualSource(
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
            platform=_val("platform"),
            edition=_val("edition", "Standard") or "Standard",
            cars_count=_int("cars_count"),
            credits_count=_int("credits_count"),
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
