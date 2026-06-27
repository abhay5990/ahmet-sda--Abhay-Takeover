"""Parse manual-entry payloads for the Brawl Stars slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class BsManualSource:
    """Normalized Brawl Stars fields from manual input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    title: str = ""
    description: str = ""

    # Categorical (stays as select slug)
    rank: str = "other"

    # Integer counts (UI sends numbers, pipeline resolves to marketplace slugs)
    trophies: int = 0
    brawlers: int = 0
    maxed_brawlers: int = 0
    skins: int = 0
    prestige: int = 0
    hypercharge: int = 0
    buffies: int = 0
    gems: int = 0


class BsManualSourceAdapter:
    """Extract Brawl Stars data from a manual-entry source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> BsManualSource | None:
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

        return BsManualSource(
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
            rank=_val("rank"),
            trophies=_int_val("trophies"),
            brawlers=_int_val("brawlers"),
            maxed_brawlers=_int_val("maxed_brawlers"),
            skins=_int_val("skins"),
            prestige=_int_val("prestige"),
            hypercharge=_int_val("hypercharge"),
            buffies=_int_val("buffies"),
            gems=_int_val("gems"),
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
