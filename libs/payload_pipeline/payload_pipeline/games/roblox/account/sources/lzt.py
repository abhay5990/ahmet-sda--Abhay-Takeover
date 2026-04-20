"""Parse prepared LZT payloads for the Roblox slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class RobloxLztSource:
    """Normalized Roblox fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    roblox_id: int = 0
    robux: int = 0
    incoming_robux_total: int = 0
    inventory_price: float = 0.0
    ugc_limited_price: float = 0.0
    limited_price: float = 0.0
    offsale_count: int = 0
    friends: int = 0
    followers: int = 0
    age_verified: bool = False
    email_verified: bool = False
    verified: bool = False
    register_date: int = 0
    country: str = ""
    has_subscription: bool = False
    voice_enabled: bool = False
    xbox_connected: bool = False
    psn_connected: bool = False
    username: str = ""
    game_pass_total_robux: int = 0


class RobloxLztSourceAdapter:
    """Extract Roblox data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> RobloxLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        return RobloxLztSource(
            item_id=str(payload.get("item_id") or payload.get("roblox_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            roblox_id=self._to_int(payload.get("roblox_id"), default=0),
            robux=self._to_int(payload.get("roblox_robux"), default=0),
            incoming_robux_total=self._to_int(payload.get("roblox_incoming_robux_total"), default=0),
            inventory_price=self._to_float(payload.get("roblox_inventory_price"), default=0.0),
            ugc_limited_price=self._to_float(payload.get("roblox_ugc_limited_price"), default=0.0),
            limited_price=self._to_float(payload.get("roblox_limited_price"), default=0.0),
            offsale_count=self._to_int(payload.get("roblox_offsale_count"), default=0),
            friends=self._to_int(payload.get("roblox_friends"), default=0),
            followers=self._to_int(payload.get("roblox_followers"), default=0),
            age_verified=bool(payload.get("roblox_age_verified")),
            email_verified=bool(payload.get("roblox_email_verified")),
            verified=bool(payload.get("roblox_verified")),
            register_date=self._to_int(payload.get("roblox_register_date"), default=0),
            country=str(payload.get("roblox_country") or "").strip().lower(),
            has_subscription=bool(payload.get("roblox_subscription")),
            voice_enabled=bool(payload.get("roblox_voice")),
            xbox_connected=bool(payload.get("roblox_xbox_connected")),
            psn_connected=bool(payload.get("roblox_psn_connected")),
            username=str(payload.get("roblox_username") or "").strip(),
            game_pass_total_robux=self._to_int(payload.get("roblox_game_pass_total_robux"), default=0),
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
