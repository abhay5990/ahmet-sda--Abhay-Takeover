"""Parse manual-entry payloads for the Rust slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class RustManualSource:
    """Normalized Rust fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    title: str = ""
    description: str = ""

    platform: str = ""

    # Eldorado attribute select IDs
    premium_status: str = "premium-no"
    hours_range: str = "hours-099"
    skins_range: str = "skins-014"
    steam_level_range: str = "level-05"

    # GameBoost numeric fields
    real_hours: int = 0
    skins_count: int = 0
    steam_level: int = 0


class RustManualSourceAdapter:
    """Extract Rust data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> RustManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}
        offer_details = payload.get("offer_details") or {}
        if not isinstance(offer_details, dict):
            offer_details = {}
        # The stock-start UI submits values under ``manual_fields`` (see
        # RUST_MANUAL_FIELDS). Older/dropship payloads use ``offer_details`` or
        # top-level keys, so read all three (manual_fields wins).
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

        return RustManualSource(
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
            premium_status=self._premium_to_attr(_val("premium_status", "No")),
            hours_range=_val("hours_range", "hours-099"),
            skins_range=_val("skins_range", "skins-014"),
            steam_level_range=_val("steam_level_range", "level-05"),
            real_hours=_int("real_hours"),
            skins_count=_int("skins_count"),
            steam_level=_int("steam_level"),
        )

    @staticmethod
    def _premium_to_attr(value: str) -> str:
        """Map the UI's Yes/No premium selection to Eldorado's attribute id.

        Accepts either the human option ("Yes"/"No") the stock UI submits or an
        already-resolved Eldorado id ("premium-yes"/"premium-no"/"premium-other").
        """
        normalized = value.strip().lower()
        if normalized in ("yes", "premium-yes", "true"):
            return "premium-yes"
        if normalized in ("no", "premium-no", "false", ""):
            return "premium-no"
        if normalized.startswith("premium-"):
            return normalized
        return "premium-other"

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
