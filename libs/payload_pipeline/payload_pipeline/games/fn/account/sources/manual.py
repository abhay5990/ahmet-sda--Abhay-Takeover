"""Parse manual-entry payloads for the Fortnite slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class FortniteManualSource:
    """Normalized Fortnite fields from manual (Google Sheet) input."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    level: int = 500
    platform: str = "PC"
    platforms: list[str] = field(default_factory=lambda: ["PC"])
    skin_count: int = 0
    pickaxe_count: int = 0
    dance_count: int = 0
    glider_count: int = 0
    v_bucks: int = 0
    lifetime_wins: int = 0
    backpack_count: int = 0
    wrap_count: int = 0
    banner_count: int = 0
    spray_count: int = 0
    exclusive_count: int = 0

    psn_linkable: bool = False
    xbox_linkable: bool = False

    title: str = ""
    description: str = ""
    images: str = ""  # Imgur album URL


class FortniteManualSourceAdapter:
    """Extract Fortnite data from a manual-entry source envelope (Google Sheet)."""

    def parse(self, raw_data: dict[str, Any] | None) -> FortniteManualSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        # Parsed items from the sheet reader
        parsed_items = payload.get("parsed_items") or {}

        # Platform resolution
        platforms = payload.get("platforms", ["PC"])
        main_platform = payload.get("main_platform") or (platforms[0] if platforms else "PC")

        # Derive linkability from platforms list
        psn_linkable = "PSN" in platforms
        xbox_linkable = "XBOX" in platforms

        price = self._to_float(payload.get("price"), default=0.0)

        return FortniteManualSource(
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
            level=self._to_int(parsed_items.get("level") or payload.get("level"), default=500),
            platform=str(main_platform).strip(),
            platforms=platforms,
            skin_count=self._to_int(parsed_items.get("outfits"), default=0),
            pickaxe_count=self._to_int(parsed_items.get("pickaxes"), default=0),
            dance_count=self._to_int(parsed_items.get("emotes"), default=0),
            glider_count=self._to_int(parsed_items.get("gliders"), default=0),
            v_bucks=0,
            lifetime_wins=self._to_int(parsed_items.get("wins") or payload.get("wins"), default=0),
            backpack_count=self._to_int(parsed_items.get("backpacks"), default=0),
            wrap_count=self._to_int(parsed_items.get("wraps"), default=0),
            banner_count=self._to_int(parsed_items.get("banners"), default=0),
            spray_count=self._to_int(parsed_items.get("sprays"), default=0),
            exclusive_count=self._to_int(parsed_items.get("exclusives"), default=0),
            psn_linkable=psn_linkable,
            xbox_linkable=xbox_linkable,
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            images=str(payload.get("images") or "").strip(),
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
