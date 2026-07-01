"""Resolve R6 account data from multiple prepared sources."""

from __future__ import annotations

from . import skin_lookup
from .models import R6InventoryBreakdown, R6InventoryCategory, R6ResolvedAccount
from .rank_parsing import normalize_rank, pick_best_rank
from .source_normalization import R6RankSignal, R6WeaponSkin
from .sources import R6LztSourceAdapter, R6ManualSourceAdapter, R6TrackerSourceAdapter
from .sources.lzt import R6LztSource
from .sources.tracker import R6TrackerSource, TrackerItem
from ....core.contracts import PipelineRequest
from ....core import context_keys as ctx
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class R6Resolver:
    """Owns source precedence and merge decisions for R6."""

    def __init__(self) -> None:
        self.lzt = R6LztSourceAdapter()
        self.tracker = R6TrackerSourceAdapter()
        self._manual = R6ManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> R6ResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        lzt = self.lzt.parse(request.source("lzt"))
        tracker = self.tracker.parse(request.source("tracker"))

        if lzt is None and tracker is None:
            raise SourceValidationError("R6 requires at least one source: 'manual', 'lzt', or 'tracker'.")

        credentials = self._resolve_credentials(request.kind, lzt, tracker)
        level = tracker.level if tracker and tracker.level > 0 else (lzt.level if lzt else 0)
        current_rank, current_rank_source = self._resolve_current_rank(tracker, lzt)
        peak_rank, peak_rank_count, peak_rank_source = self._resolve_peak_rank(
            tracker,
            lzt,
            current_rank,
        )

        operators = self._dedupe(lzt.operators if lzt else [])
        operator_count = lzt.operator_count if lzt and lzt.operator_count > 0 else len(operators)

        preferred_skins = self._resolve_preferred_weapon_skins(lzt, tracker)
        skin_names = [skin.name for skin in preferred_skins if skin.name]
        skin_count = self._resolve_skin_count(lzt, tracker)
        black_ice_count = self._resolve_black_ice_count(lzt, tracker, preferred_skins)

        psn_connected, xbox_connected = self._resolve_platform_connections(lzt, tracker)

        # Tracker-only overrides (injected by orchestrator for sheet imports)
        tracker_raw = request.source("tracker")
        _tr = tracker_raw if isinstance(tracker_raw, dict) else {}

        # Price: prefer LZT, then tracker source (injected by orchestrator)
        price = lzt.price if lzt else 0.0
        if price == 0 and _tr.get("price"):
            try:
                price = float(_tr["price"])
            except (TypeError, ValueError):
                pass

        # Title/description overrides from sheet (tracker-only mode)
        sheet_title = str(_tr.get("_sheet_title") or "").strip()
        sheet_desc = str(_tr.get("_sheet_description") or "").strip()

        return R6ResolvedAccount(
            item_id=lzt.item_id if lzt else "",
            category_id=lzt.category_id if lzt else 5,
            price=price,
            kind=request.kind,
            credentials=credentials,
            tracker_url=self._resolve_tracker_url(request, lzt, tracker),
            level=level,
            current_rank=current_rank,
            current_rank_source=current_rank_source,
            peak_rank=peak_rank,
            peak_rank_count=peak_rank_count,
            peak_rank_source=peak_rank_source,
            operators=operators,
            operator_count=operator_count,
            skin_names=self._dedupe(skin_names),
            skin_count=skin_count,
            black_ice_count=black_ice_count,
            marketplace_value=tracker.marketplace_value if tracker else 0,
            renown=tracker.renown if tracker else 0,
            credits=tracker.credits if tracker else 0,
            ownership_state=lzt.ownership_state if lzt else "unknown",
            has_game=lzt.has_game if lzt else None,
            use_fixed_price=bool(tracker and not lzt),
            inventory=self._build_inventory_breakdown(tracker),
            psn_connected=psn_connected,
            xbox_connected=xbox_connected,
            manual_title=sheet_title,
            manual_description=sheet_desc,
        )

    def _resolve_manual(self, src, request: PipelineRequest) -> R6ResolvedAccount:
        credentials = resolve_credentials(src, kind=request.kind, game_name="R6")

        ownership = "unknown"
        if src.game_purchased in ("yes", "purchased-yes"):
            ownership = "owned"
        elif src.game_purchased in ("no", "purchased-no"):
            ownership = "external"

        return R6ResolvedAccount(
            item_id=src.item_id,
            category_id=src.category_id,
            price=src.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=src.title,
            manual_description=src.description,
            ownership_state=ownership,
            has_game=src.game_purchased in ("yes", "purchased-yes") if src.game_purchased != "other" else None,
            # Integer counts from manual entry
            operator_count=src.operators,
            renown=src.renown,
            black_ice_count=src.black_ice_skins,
            # Pass manual attribute slugs for marketplace builders
            current_rank_attr=src.current_rank if src.current_rank != "other" else "",
            previous_rank_attr=src.previous_rank if src.previous_rank != "other" else "",
            game_purchased_attr=src.game_purchased if src.game_purchased != "other" else "",
            ranked_unlocked_attr=src.ranked_unlocked if src.ranked_unlocked != "other" else "",
        )

    def _resolve_credentials(self, kind, lzt, tracker):
        return resolve_credentials(lzt, tracker, kind=kind, game_name="R6")

    def _resolve_platform_connections(
        self,
        lzt: R6LztSource | None,
        tracker: R6TrackerSource | None,
    ) -> tuple[bool, bool]:
        psn = (lzt.psn_connected if lzt else False) or (tracker.psn_linked if tracker else False)
        xbox = (lzt.xbox_connected if lzt else False) or (tracker.xbox_linked if tracker else False)
        return psn, xbox

    def _resolve_current_rank(
        self,
        tracker: R6TrackerSource | None,
        lzt: R6LztSource | None,
    ) -> tuple[str, str]:
        tracker_signal = self._select_current_rank_signal(
            tracker.rank_signals if tracker else [],
            preferred_sources=("tracker_charm", "tracker_rank"),
        )
        if tracker_signal is not None:
            return tracker_signal.rank, tracker_signal.source

        lzt_signal = self._select_current_rank_signal(
            lzt.rank_signals if lzt else [],
            preferred_sources=("lzt_rank",),
        )
        if lzt_signal is not None:
            return lzt_signal.rank, lzt_signal.source

        return "Unranked", ""

    def _resolve_peak_rank(
        self,
        tracker: R6TrackerSource | None,
        lzt: R6LztSource | None,
        current_rank: str,
    ) -> tuple[str, int, str]:
        tracker_peak = self._select_peak_rank(
            tracker.rank_signals if tracker else [],
            allowed_sources=("tracker_charm", "tracker_rank"),
        )
        if tracker_peak is not None:
            return tracker_peak

        lzt_peak = self._select_peak_rank(
            lzt.rank_signals if lzt else [],
            allowed_sources=("lzt_title",),
        )
        if lzt_peak is not None:
            return lzt_peak

        current = normalize_rank(current_rank) or "Unranked"
        if current.lower() != "unranked":
            return current, 1, "current_rank"
        return "Unranked", 0, ""

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = str(value).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
        return result

    def _resolve_preferred_weapon_skins(
        self,
        lzt: R6LztSource | None,
        tracker: R6TrackerSource | None,
    ) -> list[R6WeaponSkin]:
        if tracker and tracker.weapon_skins:
            return list(tracker.weapon_skins)
        if lzt and lzt.weapon_skins:
            return list(lzt.weapon_skins)
        return []

    def _resolve_skin_count(
        self,
        lzt: R6LztSource | None,
        tracker: R6TrackerSource | None,
    ) -> int:
        if lzt and lzt.skin_count > 0:
            return lzt.skin_count
        if lzt and lzt.weapon_skins:
            return len(lzt.weapon_skins)
        if tracker and tracker.weapon_skins:
            return len(tracker.weapon_skins)
        return 0

    def _resolve_black_ice_count(
        self,
        lzt: R6LztSource | None,
        tracker: R6TrackerSource | None,
        preferred_skins: list[R6WeaponSkin],
    ) -> int:
        preferred_black_ice = self._count_weapon_skin_bucket(preferred_skins, "black_ice")
        if preferred_black_ice > 0:
            return preferred_black_ice

        if tracker and tracker.weapon_skins:
            return tracker.black_ice_count

        if lzt and lzt.weapon_skins:
            black_ice = self._count_weapon_skin_bucket(lzt.weapon_skins, "black_ice")
            if black_ice > 0:
                return black_ice

        if lzt and lzt.skin_ids:
            return skin_lookup.count_black_ice(lzt.skin_ids)

        skin_names = [skin.name for skin in preferred_skins if skin.name]
        return sum(1 for skin in skin_names if "black ice" in skin.lower())

    def _build_inventory_breakdown(self, tracker: R6TrackerSource | None) -> R6InventoryBreakdown:
        if tracker is None or not tracker.inventory:
            return R6InventoryBreakdown()

        inv = tracker.inventory

        def _cat(key: str) -> R6InventoryCategory:
            items = inv.get(key, [])
            names = [item.name for item in items if item.name]
            return R6InventoryCategory(count=len(names), items=names)

        # Merge Pro Leagues (New) and Pro Leagues into one
        pro_new_items = inv.get("Pro Leagues (New)", []) + inv.get("Pro Leagues", [])
        seen_pro: set[str] = set()
        pro_new_names: list[str] = []
        for item in pro_new_items:
            if item.name and item.name not in seen_pro:
                seen_pro.add(item.name)
                pro_new_names.append(item.name)

        # Collect used item names to find "other" skins
        used: set[str] = set()
        glaciers = _cat("Glaciers")
        black_ices = _cat("Black Ices")
        dust_lines = _cat("Dust Lines")
        universals = _cat("Universals")
        seasonals = _cat("Seasonals")
        pro_leagues_old = _cat("Pro Leagues (Old)")
        elites = _cat("Elites")
        legendary_skins = _cat("Legendary Weapon Skins")
        ranked_charms = _cat("Ranked Charms")
        pilot_program = _cat("Pilot Program")

        for cat in (glaciers, black_ices, dust_lines, universals, seasonals,
                    pro_leagues_old, elites, legendary_skins, ranked_charms, pilot_program):
            used.update(cat.items)
        used.update(pro_new_names)

        other_skins = self._get_unused_skins(inv, used)

        return R6InventoryBreakdown(
            glaciers=glaciers,
            black_ices=black_ices,
            dust_lines=dust_lines,
            universals=universals,
            seasonals=seasonals,
            pro_leagues_old=pro_leagues_old,
            pro_leagues_new=R6InventoryCategory(count=len(pro_new_names), items=pro_new_names),
            pilot_program=pilot_program,
            elites=elites,
            legendary_skins=legendary_skins,
            ranked_charms=ranked_charms,
            other_skins=other_skins,
        )

    def _get_unused_skins(
        self,
        inventory: dict[str, list[TrackerItem]],
        used: set[str],
    ) -> list[str]:
        categories = ["Epic Weapon Skins", "Rare Weapon Skins", "Uncommon Weapon Skins"]
        unused: list[str] = []
        seen: set[str] = set()
        for category in categories:
            for item in inventory.get(category, []):
                if item.name and item.name not in used and item.name not in seen:
                    unused.append(item.name)
                    seen.add(item.name)
        return unused

    def _count_weapon_skin_bucket(self, skins: list[R6WeaponSkin], bucket: str) -> int:
        return sum(1 for skin in skins if skin.bucket == bucket)

    def _select_current_rank_signal(
        self,
        signals: list[R6RankSignal],
        *,
        preferred_sources: tuple[str, ...],
    ) -> R6RankSignal | None:
        source_priority = {source: index for index, source in enumerate(preferred_sources)}
        candidates = [
            signal
            for signal in signals
            if signal.is_current_candidate and normalize_rank(signal.rank) and signal.rank.lower() != "unranked"
        ]
        if not candidates:
            return None

        return min(
            candidates,
            key=lambda signal: (
                source_priority.get(signal.source, len(source_priority)),
                -int(signal.order),
            ),
        )

    def _select_peak_rank(
        self,
        signals: list[R6RankSignal],
        *,
        allowed_sources: tuple[str, ...],
    ) -> tuple[str, int, str] | None:
        candidates = [
            signal
            for signal in signals
            if signal.source in allowed_sources and normalize_rank(signal.rank) and signal.rank.lower() != "unranked"
        ]
        if not candidates:
            return None

        peak_rank = pick_best_rank(*(signal.rank for signal in candidates))
        if not peak_rank:
            return None

        count = sum(signal.count for signal in candidates if signal.rank == peak_rank)
        primary_signal = min(
            [signal for signal in candidates if signal.rank == peak_rank],
            key=lambda signal: signal.order,
        )
        return peak_rank, max(1, count), primary_signal.source

    def _resolve_tracker_url(
        self,
        request: PipelineRequest,
        lzt: R6LztSource | None,
        tracker: R6TrackerSource | None,
    ) -> str:
        # Explicit context override takes top priority
        tracker_url = str(request.context.get(ctx.TRACKER_URL) or "").strip()
        if tracker_url:
            return tracker_url

        # LZT sometimes carries a pre-built tracker link
        if lzt and lzt.tracker_url:
            return lzt.tracker_url

        # Build URL from resolved tracker source fields
        if tracker is not None:
            if tracker.masked_id:
                return f"r6skins.locker/masked/{tracker.masked_id}"

            if tracker.username.lower() == "masked" and tracker.user_id:
                return f"r6skins.locker/masked/{tracker.user_id}"

            if tracker.user_id:
                return f"r6skins.locker/profile/{tracker.user_id}"

        # Fallback to LZT uplay_id
        if lzt and lzt.uplay_id:
            return f"r6skins.locker/profile/{lzt.uplay_id}"

        return ""
