"""Parse manual-entry payloads for the CS2 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class CS2ManualSource:
    """Normalized CS2 fields from manual entry."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    title: str = ""
    description: str = ""
    images: str = ""

    # Eldorado attributes (select)
    veteran_coin: str = "other"
    esea_rating: str = "other"
    faceit_level: str = "other"
    prime_status: str = "other"  # "active-prime", "non-prime", "other"

    # Numeric fields
    premier_rating: int = 0
    medals: int = 0


class CS2ManualSourceAdapter:
    """Extract CS2 data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> CS2ManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        mf = payload.get("manual_fields") if isinstance(payload.get("manual_fields"), dict) else {}
        offer_details = payload.get("offer_details") if isinstance(payload.get("offer_details"), dict) else {}

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
                    return self._to_int(v, default)
            return default

        price = self._to_float(payload.get("price"), default=0.0)

        return CS2ManualSource(
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
            veteran_coin=_val("veteran_coin"),
            esea_rating=_val("esea_rating"),
            faceit_level=_val("faceit_level"),
            prime_status=_val("prime_status"),
            premier_rating=_int_val("premier_rating"),
            medals=_int_val("medals"),
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
