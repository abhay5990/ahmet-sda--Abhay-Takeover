"""Parse manual-entry payloads for the Ubisoft Connect slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class UbisoftConnectManualSource:
    """Normalized Ubisoft Connect fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    title: str = ""
    description: str = ""
    credentials: CredentialBundle = field(default_factory=CredentialBundle)


class UbisoftConnectManualSourceAdapter:
    """Extract Ubisoft Connect data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> UbisoftConnectManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        price = self._to_float(payload.get("price"), default=0.0)

        return UbisoftConnectManualSource(
            item_id=str(payload.get("item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=price,
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
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
