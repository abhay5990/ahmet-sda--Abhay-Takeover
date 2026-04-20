"""Parse prepared tracker payloads for the R6 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rank_parsing import extract_rank_from_text, normalize_rank, pick_best_rank
from ..source_normalization import (
    R6RankSignal,
    R6WeaponSkin,
    build_skin_key,
    is_tracker_weapon_skin_item,
    normalize_skin_bucket,
)
from .....core.contracts import CredentialBundle


@dataclass(slots=True)
class TrackerItem:
    """Single parsed inventory item from tracker."""

    name: str
    asset_id: str = ""
    image_url: str = ""


@dataclass(slots=True)
class TrackerSocialLink:
    """One linked social profile exposed by the tracker payload."""

    username: str = ""
    ghost_linked: bool = False


@dataclass(slots=True)
class RankedCharmLite:
    """Lightweight ranked-charm entry used for rank history resolution."""

    name: str
    rank: str = ""
    season: str = ""


@dataclass(slots=True)
class R6TrackerInventorySummary:
    """Convenience summary derived from tracker inventory categories."""

    ranked_charm_count: int = 0
    black_ice_count: int = 0
    glacier_count: int = 0
    gold_dust_count: int = 0
    dust_line_count: int = 0
    universal_count: int = 0
    seasonal_count: int = 0
    pro_league_old_count: int = 0
    pro_league_new_count: int = 0
    elite_count: int = 0
    legendary_count: int = 0
    pilot_program_count: int = 0


@dataclass(slots=True)
class R6TrackerSource:
    """Normalized R6 fields extracted from tracker payloads."""

    credentials: CredentialBundle = field(default_factory=CredentialBundle)
    level: int = 0
    rank: str = ""
    peak_rank: str = ""
    peak_rank_count: int = 0
    marketplace_value: int = 0
    renown: int = 0
    credits: int = 0

    inventory: dict[str, list[TrackerItem]] = field(default_factory=dict)
    weapon_skins: list[R6WeaponSkin] = field(default_factory=list)
    ranked_charms_lite: list[RankedCharmLite] = field(default_factory=list)
    rank_signals: list[R6RankSignal] = field(default_factory=list)
    inventory_summary: R6TrackerInventorySummary = field(default_factory=R6TrackerInventorySummary)

    psn_linked: bool = False
    xbox_linked: bool = False
    psn_profile: TrackerSocialLink = field(default_factory=TrackerSocialLink)
    xbox_profile: TrackerSocialLink = field(default_factory=TrackerSocialLink)

    masked_id: str = ""
    user_id: str = ""
    username: str = ""
    is_masked: bool = False

    banned: bool = False
    ban_source: str = ""
    ban_expiration: str = ""
    created_at: str = ""
    added_at: str = ""

    @property
    def weapon_skin_names(self) -> list[str]:
        return [skin.name for skin in self.weapon_skins if skin.name]

    @property
    def black_ice_count(self) -> int:
        black_ice = sum(1 for skin in self.weapon_skins if skin.bucket == "black_ice")
        if black_ice > 0:
            return black_ice
        if self.inventory_summary.black_ice_count > 0:
            return self.inventory_summary.black_ice_count
        return sum(1 for name in self.weapon_skin_names if "black ice" in name.lower())


class R6TrackerSourceAdapter:
    """Extract R6 data from a prepared tracker source envelope."""

    def parse(self, raw_data: dict[str, Any] | None) -> R6TrackerSource | None:
        if not isinstance(raw_data, dict) or not raw_data:
            return None

        login_data = raw_data.get("loginData") if isinstance(raw_data.get("loginData"), dict) else {}
        email_data = raw_data.get("emailLoginData") if isinstance(raw_data.get("emailLoginData"), dict) else {}
        socials = raw_data.get("socials") if isinstance(raw_data.get("socials"), dict) else {}
        inventory = self._parse_inventory(raw_data.get("inventory"))
        weapon_skins = self._build_weapon_skins(inventory)
        inventory_summary = self._build_inventory_summary(inventory)
        ranked_charms_lite = self._parse_ranked_charms(inventory.get("Ranked Charms", []))
        rank_signals = self._build_rank_signals(raw_data, ranked_charms_lite)

        username = str(raw_data.get("username") or "").strip()
        user_id = str(raw_data.get("userId") or "").strip()
        masked_id = str(raw_data.get("maskedId") or "").strip()
        is_masked = username.lower() == "masked"
        if not masked_id and is_masked:
            masked_id = user_id

        psn_profile = self._parse_social_link(socials.get("psn"))
        xbox_profile = self._parse_social_link(socials.get("xbl"))

        return R6TrackerSource(
            credentials=CredentialBundle(
                login=str(login_data.get("login") or raw_data.get("login") or "").strip(),
                password=str(login_data.get("password") or raw_data.get("password") or "").strip(),
                email_login=str(email_data.get("login") or raw_data.get("emailLogin") or "").strip(),
                email_password=str(email_data.get("password") or raw_data.get("emailPassword") or "").strip(),
            ),
            level=self._to_int(raw_data.get("level"), default=0),
            rank=self._resolve_current_rank(raw_data, ranked_charms_lite),
            peak_rank=self._resolve_peak_rank(ranked_charms_lite),
            peak_rank_count=self._resolve_peak_rank_count(ranked_charms_lite),
            marketplace_value=self._to_int(
                raw_data.get("marketplaceValue", raw_data.get("marketplace_value")),
                default=0,
            ),
            renown=self._to_int((raw_data.get("currency") or {}).get("renown"), default=0)
            if isinstance(raw_data.get("currency"), dict)
            else 0,
            credits=self._to_int((raw_data.get("currency") or {}).get("credits"), default=0)
            if isinstance(raw_data.get("currency"), dict)
            else 0,
            inventory=inventory,
            weapon_skins=weapon_skins,
            ranked_charms_lite=ranked_charms_lite,
            rank_signals=rank_signals,
            inventory_summary=inventory_summary,
            psn_linked=bool(psn_profile.username),
            xbox_linked=bool(xbox_profile.username),
            psn_profile=psn_profile,
            xbox_profile=xbox_profile,
            masked_id=masked_id,
            user_id=user_id,
            username=username,
            is_masked=is_masked,
            banned=bool(raw_data.get("banned")),
            ban_source=str(raw_data.get("banSource") or "").strip(),
            ban_expiration=str(raw_data.get("banExpiration") or "").strip(),
            created_at=str(raw_data.get("created_at") or raw_data.get("createdAt") or "").strip(),
            added_at=str(raw_data.get("added_at") or raw_data.get("addedAt") or "").strip(),
        )

    def _parse_inventory(self, raw_inventory: Any) -> dict[str, list[TrackerItem]]:
        if not isinstance(raw_inventory, dict):
            return {}

        parsed: dict[str, list[TrackerItem]] = {}
        for category, items in raw_inventory.items():
            if not isinstance(items, list):
                continue
            bucket: list[TrackerItem] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                bucket.append(
                    TrackerItem(
                        name=str(item.get("name") or "").strip(),
                        asset_id=str(item.get("assetId") or item.get("asset_id") or "").strip(),
                        image_url=str(item.get("imageUrl") or item.get("image_url") or "").strip(),
                    )
                )
            if bucket:
                parsed[str(category)] = bucket
        return parsed

    def _build_weapon_skins(
        self,
        inventory: dict[str, list[TrackerItem]],
    ) -> list[R6WeaponSkin]:
        skins: list[R6WeaponSkin] = []
        seen: set[str] = set()

        for category, items in inventory.items():
            for item in items:
                if not is_tracker_weapon_skin_item(category, item.name):
                    continue

                record = R6WeaponSkin(
                    key=build_skin_key(source="tracker", source_id=item.asset_id, name=item.name),
                    source="tracker",
                    name=item.name,
                    source_id=item.asset_id,
                    image_url=item.image_url,
                    bucket=normalize_skin_bucket(category, name=item.name),
                    category=category,
                )
                if record.key in seen:
                    continue
                seen.add(record.key)
                skins.append(record)

        return skins

    def _parse_ranked_charms(self, items: list[TrackerItem]) -> list[RankedCharmLite]:
        parsed: list[RankedCharmLite] = []
        for item in items:
            name = str(item.name or "").strip()
            if not name:
                continue
            rank = extract_rank_from_text(name)
            if not rank:
                continue
            parsed.append(
                RankedCharmLite(
                    name=name,
                    rank=rank,
                    season=self._extract_season(name),
                )
            )
        return parsed

    def _build_rank_signals(
        self,
        raw_data: dict[str, Any],
        ranked_charms_lite: list[RankedCharmLite],
    ) -> list[R6RankSignal]:
        signals: list[R6RankSignal] = []
        direct_rank = normalize_rank(raw_data.get("rank"))
        if direct_rank:
            signals.append(
                R6RankSignal(
                    rank=direct_rank,
                    source="tracker_rank",
                    count=1,
                    order=0,
                    is_current_candidate=True,
                )
            )

        offset = len(signals)
        for index, item in enumerate(ranked_charms_lite, start=1):
            signals.append(
                R6RankSignal(
                    rank=item.rank,
                    source="tracker_charm",
                    count=1,
                    season=item.season,
                    order=offset + index,
                    is_current_candidate=index == len(ranked_charms_lite),
                )
            )

        return signals

    def _build_inventory_summary(
        self,
        inventory: dict[str, list[TrackerItem]],
    ) -> R6TrackerInventorySummary:
        return R6TrackerInventorySummary(
            ranked_charm_count=len(inventory.get("Ranked Charms", [])),
            black_ice_count=len(inventory.get("Black Ices", [])),
            glacier_count=len(inventory.get("Glaciers", [])),
            gold_dust_count=len(inventory.get("Gold Dusts", [])),
            dust_line_count=len(inventory.get("Dust Lines", [])),
            universal_count=len(inventory.get("Universals", [])),
            seasonal_count=len(inventory.get("Seasonals", [])),
            pro_league_old_count=len(inventory.get("Pro Leagues (Old)", [])),
            pro_league_new_count=(
                len(inventory.get("Pro Leagues (New)", [])) + len(inventory.get("Pro Leagues", []))
            ),
            elite_count=len(inventory.get("Elites", [])),
            legendary_count=len(inventory.get("Legendary Weapon Skins", [])),
            pilot_program_count=(
                len(inventory.get("Y4 Pilot Programs", []))
                + len(inventory.get("Y5 Pilot Programs", []))
                + len(inventory.get("Y6 Pilot Programs", []))
                + len(inventory.get("Y7 Pilot Programs", []))
                + len(inventory.get("Y8 Pilot Programs", []))
                + len(inventory.get("Y9 Pilot Programs", []))
                + len(inventory.get("Pilot Program", []))
            ),
        )

    def _resolve_current_rank(
        self,
        raw_data: dict[str, Any],
        ranked_charms_lite: list[RankedCharmLite],
    ) -> str:
        direct_rank = normalize_rank(raw_data.get("rank"))
        if direct_rank:
            return direct_rank
        if ranked_charms_lite:
            return ranked_charms_lite[-1].rank
        return ""

    def _resolve_peak_rank(self, ranked_charms_lite: list[RankedCharmLite]) -> str:
        return pick_best_rank(*(item.rank for item in ranked_charms_lite))

    def _resolve_peak_rank_count(self, ranked_charms_lite: list[RankedCharmLite]) -> int:
        peak_rank = self._resolve_peak_rank(ranked_charms_lite)
        if not peak_rank:
            return 0
        return sum(1 for item in ranked_charms_lite if item.rank == peak_rank)

    def _parse_social_link(self, value: Any) -> TrackerSocialLink:
        if isinstance(value, dict):
            return TrackerSocialLink(
                username=str(value.get("username") or "").strip(),
                ghost_linked=bool(value.get("ghost_linked")),
            )
        if isinstance(value, str):
            return TrackerSocialLink(username=value.strip())
        return TrackerSocialLink()

    def _extract_season(self, value: str) -> str:
        if "(" not in value or ")" not in value:
            return ""
        return value.split("(", 1)[1].split(")", 1)[0].strip()

    def _to_int(self, value: Any, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return int(str(value).strip().rstrip("+"))
        except (TypeError, ValueError):
            return default
