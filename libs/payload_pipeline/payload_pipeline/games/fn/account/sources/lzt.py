"""Parse prepared LZT payloads for the Fortnite slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class FortniteLztSource:
    """Normalized Fortnite fields from LZT."""

    item_id: str = ""
    category_id: int = 1
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    level: int = 0
    platform: str = ""
    skin_count: int = 0
    pickaxe_count: int = 0
    dance_count: int = 0
    glider_count: int = 0
    v_bucks: int = 0
    lifetime_wins: int = 0
    battle_pass_level: int = 0
    season_num: int = 0
    refund_credits: int = 0
    has_real_purchases: bool = False
    psn_linkable: bool = False
    xbox_linkable: bool = False
    fortnite_next_change_email_date: int = 0
    cosmetic_titles: list[str] = field(default_factory=list)
    cosmetics_by_category: dict[str, list[str]] = field(default_factory=dict)
    preview_urls: dict[str, str] = field(default_factory=dict)


class FortniteLztSourceAdapter:
    """Extract Fortnite data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> FortniteLztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = payload.get("emailLoginData") if isinstance(payload.get("emailLoginData"), dict) else {}

        return FortniteLztSource(
            item_id=str(payload.get("item_id") or payload.get("fortnite_item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=1),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            level=self._to_int(payload.get("fortnite_level"), default=0),
            platform=str(payload.get("fortnite_platform") or "").strip(),
            skin_count=self._to_int(payload.get("fortnite_skin_count") or payload.get("fortnite_shop_skins_count"), default=0),
            pickaxe_count=self._to_int(payload.get("fortnite_shop_pickaxes_count"), default=0),
            dance_count=self._to_int(payload.get("fortnite_shop_dances_count"), default=0),
            glider_count=self._to_int(payload.get("fortnite_shop_gliders_count"), default=0),
            v_bucks=self._to_int(payload.get("fortnite_balance"), default=0),
            lifetime_wins=self._to_int(payload.get("fortnite_lifetime_wins"), default=0),
            battle_pass_level=self._to_int(payload.get("fortnite_book_level"), default=0),
            season_num=self._to_int(payload.get("fortnite_season_num"), default=0),
            refund_credits=self._to_int(payload.get("fortnite_refund_credits"), default=0),
            has_real_purchases=bool(payload.get("fortnite_rl_purchases")),
            psn_linkable=bool(payload.get("fortnite_psn_linkable")),
            xbox_linkable=bool(payload.get("fortnite_xbox_linkable")),
            fortnite_next_change_email_date=self._to_int(payload.get("fortnite_next_change_email_date"), default=0),
            cosmetic_titles=self._extract_cosmetic_titles(payload),
            cosmetics_by_category=self._extract_cosmetics_by_category(payload),
            preview_urls=self._resolve_preview_urls(payload),
        )

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    _LZT_KEY_TO_CATEGORY: dict[str, str] = {
        "fortniteSkins":    "outfit",
        "fortnitePickaxe":  "pickaxe",
        "fortniteDance":    "emote",
        "fortniteGliders":  "glider",
    }

    @classmethod
    def _extract_cosmetic_titles(cls, payload: dict[str, Any]) -> list[str]:
        titles: list[str] = []
        for key in cls._LZT_KEY_TO_CATEGORY:
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()
                    if title:
                        titles.append(title)
        return titles

    @classmethod
    def _extract_cosmetics_by_category(cls, payload: dict[str, Any]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for key, category in cls._LZT_KEY_TO_CATEGORY.items():
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            titles = [
                str(item.get("title") or "").strip()
                for item in items
                if isinstance(item, dict) and item.get("title")
            ]
            if titles:
                result[category] = titles
        return result

    def _resolve_preview_urls(self, payload: dict[str, Any]) -> dict[str, str]:
        preview_links = payload.get("imagePreviewLinks")
        if not isinstance(preview_links, dict):
            return {}

        direct_links = preview_links.get("direct")
        if not isinstance(direct_links, dict):
            return {}

        mapping = {
            "skins": str(direct_links.get("skins") or "").strip(),
            "pickaxes": str(direct_links.get("pickaxes") or "").strip(),
            "dances": str(direct_links.get("dances") or "").strip(),
            "gliders": str(direct_links.get("gliders") or "").strip(),
        }
        return {key: value for key, value in mapping.items() if value}

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
