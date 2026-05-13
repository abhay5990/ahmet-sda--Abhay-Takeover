"""Parse manual-entry payloads for the GTA V slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class GtavManualSource:
    """Normalized GTA V fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    main_platform: str = ""
    level: int = 0
    cash_amount: int = 0
    cash_unit: str = "Million"
    cars_count: int = 0
    tags: list[str] = field(default_factory=list)
    has_dual_characters: bool = False

    security_email: str = ""
    security_email_password: str = ""
    security_email_login_link: str = ""
    birthday: str = ""
    email_backup_codes: str = ""

    title: str = "GTA V Account"
    description: str = ""

    credential_extras: dict[str, Any] = field(default_factory=dict)
    """Platform-specific credential keys (steam_id, rock_id, psn_id, etc.)."""


# Keys extracted from raw input into credential_extras
_CREDENTIAL_EXTRA_KEYS = (
    "steam_id", "steam_pass",
    "rock_id", "rock_pass",
    "psn_id", "psn_pass",
    "xbox_id", "xbox_pass",
    "dob",
)


class GtavManualSourceAdapter:
    """Extract GTA V data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> GtavManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        offer_details = payload.get("offer_details") or {}
        if not isinstance(offer_details, dict):
            offer_details = {}

        main_platform = (
            offer_details.get("main_platform")
            or payload.get("main_platform")
            or payload.get("platform", "")
        )

        cash_amount_raw = offer_details.get("cash_amount") or payload.get("cash_amount", 0)
        cash_amount = self._to_int(cash_amount_raw, default=0)

        tags_raw = offer_details.get("tags") or payload.get("tags", [])
        tags = tags_raw if isinstance(tags_raw, list) else []

        price = self._to_float(payload.get("price"), default=0.0)

        title = (
            offer_details.get("title")
            or payload.get("title", "GTA V Account")
        )
        description = (
            offer_details.get("description")
            or payload.get("description", "")
        )

        return GtavManualSource(
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
            main_platform=str(main_platform).strip(),
            level=self._to_int(offer_details.get("level") or payload.get("level"), default=0),
            cash_amount=cash_amount,
            cash_unit=str(offer_details.get("cash_unit") or payload.get("cash_unit", "Million")).strip(),
            cars_count=self._to_int(offer_details.get("cars_count") or payload.get("cars_count"), default=0),
            tags=tags,
            has_dual_characters=bool(
                offer_details.get("has_dual_characters") or payload.get("has_dual_characters", False),
            ),
            security_email=str(payload.get("security_email") or "").strip(),
            security_email_password=str(payload.get("security_email_password") or "").strip(),
            security_email_login_link=str(payload.get("security_email_login_link") or "").strip(),
            birthday=str(payload.get("birthday") or "").strip(),
            email_backup_codes=str(payload.get("email_backup_codes") or "").strip(),
            title=str(title).strip(),
            description=str(description).strip(),
            credential_extras=self._extract_credential_extras(payload),
        )

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_credential_extras(payload: dict[str, Any]) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        for key in _CREDENTIAL_EXTRA_KEYS:
            val = str(payload.get(key) or "").strip()
            if val:
                extras[key] = val
        return extras

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
