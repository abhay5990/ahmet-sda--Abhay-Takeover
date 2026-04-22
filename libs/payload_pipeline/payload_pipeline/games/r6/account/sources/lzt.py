"""Parse prepared LZT payloads for the R6 slice."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_R6SKINS_LOCKER_RE = re.compile(
    r'r6skins\.locker/(profile|masked)/([a-f0-9-]+)', re.IGNORECASE
)

from .. import skin_lookup
from ..rank_parsing import (
    extract_rank_mentions_from_title,
    normalize_rank,
    pick_best_rank,
)
from ..source_normalization import R6RankSignal, R6WeaponSkin, build_skin_key, normalize_skin_bucket
from .....core.contracts import CredentialBundle


_R6_GAME_ID = "e3d5ea9e-50bd-43b7-88bf-39794f4e3d40"


@dataclass(slots=True)
class R6LztSource:
    """Normalized R6 fields extracted from prepared LZT payloads."""

    item_id: str = ""
    category_id: int = 5
    price: float = 0.0
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    level: int = 0
    rank: str = "Unranked"
    raw_rank_value: str = ""
    title_text: str = ""
    title_rank_hint: str = ""
    title_rank_count_hint: int = 0

    operators: list[str] = field(default_factory=list)
    operator_count: int = 0
    skin_ids: list[str] = field(default_factory=list)
    skin_names: list[str] = field(default_factory=list)
    weapon_skins: list[R6WeaponSkin] = field(default_factory=list)
    skin_count: int = 0
    rank_signals: list[R6RankSignal] = field(default_factory=list)

    linked_accounts: list[str] = field(default_factory=list)
    psn_connected: bool = False
    xbox_connected: bool = False

    tracker_url: str = ""
    uplay_id: str = ""
    ownership_state: str = "unknown"
    has_game: bool | None = None

    can_change_password: bool = False
    can_change_email_password: bool = False
    email_provider: str = ""
    email_type: str = ""


class R6LztSourceAdapter:
    """Extract R6 data from a prepared LZT source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> R6LztSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data

        login_data = payload.get("loginData") if isinstance(payload.get("loginData"), dict) else {}
        email_data = self._resolve_email_data(payload)

        title_text = str(payload.get("title_en") or payload.get("title") or "").strip()
        skin_ids = self._parse_list(payload.get("uplay_r6_skins"))
        operators = self._parse_list(
            payload.get("uplay_r6_operators"),
            fallback=payload.get("r6Operators"),
        )
        linked_accounts = self._parse_linked_accounts(payload.get("uplayLinkedAccounts"))
        has_game, ownership_state = self._parse_ownership(payload.get("uplay_games"))
        resolved_rank = self._resolve_current_rank(payload)
        skin_name_map = skin_lookup.resolve_skin_name_map(skin_ids)
        skin_names = [skin_name_map[skin_id] for skin_id in skin_ids if skin_id in skin_name_map]
        title_rank_signals = self._build_title_rank_signals(title_text)
        title_rank_hint = self._resolve_title_peak_rank(title_rank_signals)
        title_rank_count_hint = self._resolve_title_peak_rank_count(title_rank_signals, title_rank_hint)

        return R6LztSource(
            item_id=str(payload.get("item_id") or "").strip(),
            category_id=self._to_int(payload.get("category_id"), default=5),
            price=self._to_float(payload.get("price"), default=0.0),
            credentials=CredentialBundle(
                login=str(login_data.get("login") or payload.get("login") or "").strip(),
                password=str(login_data.get("password") or payload.get("password") or "").strip(),
                email_login=str(email_data.get("login") or "").strip(),
                email_password=str(email_data.get("password") or "").strip(),
                email_login_link=str(payload.get("emailLoginUrl") or "").strip(),
            ),
            level=self._to_int(payload.get("uplay_r6_level"), default=0),
            rank=resolved_rank,
            raw_rank_value=str(payload.get("uplayR6Rank") or payload.get("uplay_r6_rank") or "").strip(),
            title_text=title_text,
            title_rank_hint=title_rank_hint,
            title_rank_count_hint=title_rank_count_hint,
            operators=operators,
            operator_count=self._resolve_count(
                payload.get("uplay_r6_operators_count"),
                fallback=len(operators),
            ),
            skin_ids=skin_ids,
            skin_names=skin_names,
            weapon_skins=self._build_weapon_skins(skin_ids, skin_name_map),
            skin_count=self._resolve_count(
                payload.get("uplay_r6_skins_count"),
                fallback=len(skin_ids),
            ),
            rank_signals=self._build_rank_signals(resolved_rank, title_rank_signals),
            linked_accounts=linked_accounts,
            psn_connected=self._parse_platform_connected(
                payload.get("uplay_psn_connected"),
                linked_accounts=linked_accounts,
                platform_token="psn",
            ),
            xbox_connected=self._parse_platform_connected(
                payload.get("uplay_xbox_connected"),
                linked_accounts=linked_accounts,
                platform_token="xbox",
            ),
            tracker_url=self._parse_tracker_url(payload),
            uplay_id=str(payload.get("uplay_id") or "").strip(),
            ownership_state=ownership_state,
            has_game=has_game,
            can_change_password=bool(payload.get("canChangePassword")),
            can_change_email_password=bool(payload.get("canChangeEmailPassword")),
            email_provider=str(payload.get("email_provider") or "").strip(),
            email_type=str(payload.get("email_type") or "").strip(),
        )

    def _resolve_email_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("emailLoginData", "email_login_data", "tempEmailData"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _parse_list(self, value: Any, fallback: Any = None) -> list[str]:
        if isinstance(fallback, list) and not value:
            return [
                str(item.get("name") if isinstance(item, dict) else item).strip()
                for item in fallback
                if str(item).strip()
            ]

        if isinstance(value, list):
            return [
                str(item.get("name") if isinstance(item, dict) else item).strip()
                for item in value
                if str(item).strip()
            ]

        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [
                    str(item.get("name") if isinstance(item, dict) else item).strip()
                    for item in parsed
                    if str(item).strip()
                ]

        return []

    def _parse_linked_accounts(self, value: Any) -> list[str]:
        if isinstance(value, str):
            tokens = [token.strip().upper() for token in value.split(",") if token.strip()]
        elif isinstance(value, list):
            tokens = [str(token).strip().upper() for token in value if str(token).strip()]
        else:
            tokens = []

        normalized: list[str] = []
        for token in tokens:
            if token in {"PSN", "PLAYSTATION"} and "PSN" not in normalized:
                normalized.append("PSN")
            elif token in {"XBOX", "XBL"} and "XBOX" not in normalized:
                normalized.append("XBOX")
            elif token == "PC" and "PC" not in normalized:
                normalized.append("PC")
        return normalized

    def _parse_platform_connected(
        self,
        raw_value: Any,
        *,
        linked_accounts: list[str],
        platform_token: str,
    ) -> bool:
        normalized_token = "PSN" if platform_token == "psn" else "XBOX"
        if normalized_token in linked_accounts:
            return True

        value = self._to_int(raw_value, default=0)
        return bool(value)

    def _resolve_current_rank(self, payload: dict[str, Any]) -> str:
        direct_rank = pick_best_rank(
            payload.get("uplayR6Rank"),
            payload.get("uplay_r6_rank"),
        )
        return normalize_rank(direct_rank) or "Unranked"

    def _build_title_rank_signals(self, title_text: str) -> list[R6RankSignal]:
        signals: list[R6RankSignal] = []
        for order, (rank, count, season) in enumerate(extract_rank_mentions_from_title(title_text), start=1):
            signals.append(
                R6RankSignal(
                    rank=rank,
                    source="lzt_title",
                    count=max(1, count),
                    season=season,
                    order=order,
                )
            )
        return signals

    def _resolve_title_peak_rank(self, signals: list[R6RankSignal]) -> str:
        return pick_best_rank(*(signal.rank for signal in signals))

    def _resolve_title_peak_rank_count(
        self,
        signals: list[R6RankSignal],
        target_rank: str,
    ) -> int:
        normalized_target = normalize_rank(target_rank)
        if not normalized_target:
            return 0
        return sum(signal.count for signal in signals if signal.rank == normalized_target)

    def _build_rank_signals(
        self,
        current_rank: str,
        title_rank_signals: list[R6RankSignal],
    ) -> list[R6RankSignal]:
        signals: list[R6RankSignal] = []

        normalized_current = normalize_rank(current_rank)
        if normalized_current and normalized_current.lower() != "unranked":
            signals.append(
                R6RankSignal(
                    rank=normalized_current,
                    source="lzt_rank",
                    count=1,
                    order=0,
                    is_current_candidate=True,
                )
            )

        signals.extend(title_rank_signals)

        return signals

    def _build_weapon_skins(
        self,
        skin_ids: list[str],
        skin_name_map: dict[str, str],
    ) -> list[R6WeaponSkin]:
        skins: list[R6WeaponSkin] = []
        for raw_skin_id in skin_ids:
            skin_id = str(raw_skin_id or "").strip()
            if not skin_id:
                continue

            name = skin_name_map.get(skin_id, "")
            skins.append(
                R6WeaponSkin(
                    key=build_skin_key(source="lzt", source_id=skin_id, name=name),
                    source="lzt",
                    name=name,
                    source_id=skin_id,
                    bucket=normalize_skin_bucket("", name=name),
                    category="uplay_r6_skins",
                )
            )
        return skins

    def _parse_tracker_url(self, payload: dict[str, Any]) -> str:
        tracker_link = str(payload.get("tracker_link") or "").strip()
        if tracker_link:
            return tracker_link

        for key in ("descriptionPlain", "descriptionEnPlain"):
            text = str(payload.get(key) or "").strip()
            if text:
                match = _R6SKINS_LOCKER_RE.search(text)
                if match:
                    return f"r6skins.locker/{match.group(1)}/{match.group(2)}"

        return ""

    def _parse_ownership(self, value: Any) -> tuple[bool | None, str]:
        if not isinstance(value, dict) or not value:
            return None, "unknown"

        external_game = value.get(f"{_R6_GAME_ID}_external")
        if isinstance(external_game, dict):
            abbr = str(external_game.get("abbr") or "").strip().lower()
            if "external" in abbr:
                return False, "external_not_purchased"

        steam_game = value.get(f"{_R6_GAME_ID}_steam")
        if isinstance(steam_game, dict):
            abbr = str(steam_game.get("abbr") or "").strip().lower()
            if "steam" in abbr:
                return False, "steam_not_purchased"

        return True, "has_game"

    def _resolve_count(self, value: Any, *, fallback: int) -> int:
        count = self._to_int(value, default=0)
        if count > 0:
            return count
        return max(0, fallback)

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(str(value).strip().rstrip("+"))
        except (TypeError, ValueError):
            return default

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
