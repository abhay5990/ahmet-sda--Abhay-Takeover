"""Resolve Clash Royale account data from multiple prepared sources."""

from __future__ import annotations

from typing import Any

from .models import CrResolvedAccount
from .sources import CrLztSourceAdapter, CrManualSourceAdapter, CrTrackerSourceAdapter
from .sources.lzt import CrLztSource
from .sources.manual import CrManualSource
from .sources.tracker import CrTrackerSource
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class CrResolver:
    """Multi-source resolver for Clash Royale.

    Merge strategy:
    - Manual source: highest priority, returns immediately
    - Credentials: LZT preferred, tracker fallback
    - Stats (trophies, cards, wins/losses): tracker preferred, LZT fallback
    - Metadata (price, item_id, category_id): always from LZT
    """

    def __init__(self) -> None:
        self._manual = CrManualSourceAdapter()
        self.lzt = CrLztSourceAdapter()
        self.tracker = CrTrackerSourceAdapter()

    def resolve(self, request: PipelineRequest) -> CrResolvedAccount:
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        lzt = self.lzt.parse(request.source("lzt"))
        tracker = self.tracker.parse(request.source("tracker"))

        if lzt is None and tracker is None:
            raise SourceValidationError(
                "Clash Royale requires the 'manual', 'lzt', or 'tracker' source."
            )

        return self._resolve_lzt(lzt, tracker, request)

    def _resolve_manual(
        self,
        src: CrManualSource,
        request: PipelineRequest,
    ) -> CrResolvedAccount:
        credentials = resolve_credentials(src, kind=request.kind, game_name="Clash Royale")
        return CrResolvedAccount(
            item_id=src.item_id,
            category_id=src.category_id,
            price=src.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=src.title,
            manual_description=src.description,
        )

    def _resolve_lzt(
        self,
        lzt: CrLztSource | None,
        tracker: CrTrackerSource | None,
        request: PipelineRequest,
    ) -> CrResolvedAccount:
        credentials = self._resolve_credentials(request.kind, lzt, tracker)

        # Tracker-derived aggregate stats
        cards_found = self._prefer_tracker_int(
            tracker.cards_found if tracker else 0,
            lzt.cards_found if lzt else 0,
        )
        total_wins = self._prefer_tracker_int(
            tracker.total_wins if tracker else 0,
            lzt.total_wins if lzt else 0,
        )
        total_losses = self._resolve_total_losses(lzt, tracker)

        # Peak trophies: best from either source
        lzt_peak = lzt.peak_trophies if lzt else 0
        tracker_peak = max(
            tracker.best_season_trophies if tracker else 0,
            tracker.best_season_highest_trophies if tracker else 0,
        )
        peak_trophies = max(lzt_peak, tracker_peak)

        current_trophies = lzt.trophies if lzt else 0
        arena_name = lzt.arena if lzt else ""
        cards_data = tracker.cards if tracker else {}
        level_15_cards_count = self._count_cards_with_level(cards_data, 15)
        level_14_cards_count = self._count_cards_with_level(cards_data, 14)
        elite_cards = self._elite_card_names(cards_data)
        tracker_evolution_count = self._count_evolutions(cards_data)
        lzt_evolution_count = lzt.evolved_count if lzt else 0
        evolution_count = tracker_evolution_count if tracker_evolution_count > 0 else lzt_evolution_count
        total_cards = len(cards_data)
        player_tag = lzt.player_tag if lzt else ""
        brawl_stars_tag = lzt.brawl_stars_tag if lzt else ""
        coc_tag = lzt.coc_tag if lzt else ""

        return CrResolvedAccount(
            item_id=lzt.item_id if lzt else "",
            category_id=lzt.category_id if lzt else 1,
            price=lzt.price if lzt else 0.0,
            kind=request.kind,
            credentials=credentials,
            account_level=lzt.account_level if lzt else 0,
            king_level=lzt.king_level if lzt else 0,
            trophies=current_trophies,
            current_trophies=current_trophies,
            peak_trophies=peak_trophies,
            arena=arena_name,
            arena_name=arena_name,
            total_wins=total_wins,
            total_losses=total_losses,
            arena_level=tracker.arena if tracker else 0,
            has_brawl_stars=bool(lzt and lzt.brawl_stars_level > 0),
            brawl_stars_level=lzt.brawl_stars_level if lzt else 0,
            brawl_stars_trophies=lzt.brawl_stars_trophies if lzt else 0,
            has_coc=bool(lzt and lzt.coc_th_level > 0),
            coc_th_level=lzt.coc_th_level if lzt else 0,
            coc_trophies=lzt.coc_trophies if lzt else 0,
            creation_year=lzt.creation_year if lzt else 0,
            account_creation_year=lzt.creation_year if lzt else 0,
            battle_pass_active=lzt.battle_pass_active if lzt else False,
            player_tag=player_tag,
            account_tracker_link=(
                f"https://statsroyale.com/profile/{player_tag}" if player_tag else ""
            ),
            brawl_stars_tracker_link=(
                f"https://brawltime.ninja/profile/{brawl_stars_tag}" if brawl_stars_tag else ""
            ),
            coc_tracker_link=(
                f"https://www.clashofstats.com/ru/players/{coc_tag}" if coc_tag else ""
            ),
            total_cards=total_cards,
            cards_found=cards_found,
            cards_data=cards_data,
            evolution_count=evolution_count,
            elite_cards=elite_cards,
            max_cards_count=level_14_cards_count,
            level_15_cards_count=level_15_cards_count,
            level_14_cards_count=level_14_cards_count,
            has_email_access=self._resolve_has_email(lzt, tracker),
        )

    def _resolve_credentials(self, kind, lzt, tracker):
        return resolve_credentials(lzt, tracker, kind=kind, game_name="Clash Royale")

    def _resolve_has_email(
        self,
        lzt: CrLztSource | None,
        tracker: CrTrackerSource | None,
    ) -> bool:
        if lzt and not lzt.credentials.is_empty and lzt.credentials.email_login:
            return True
        if tracker and not tracker.credentials.is_empty and tracker.credentials.email_login:
            return True
        return False

    def _prefer_tracker_int(self, tracker_val: int, lzt_val: int) -> int:
        """Use tracker value when positive, fall back to LZT."""
        return tracker_val if tracker_val > 0 else lzt_val

    def _resolve_total_losses(
        self,
        lzt: CrLztSource | None,
        tracker: CrTrackerSource | None,
    ) -> int:
        if tracker:
            if tracker.losses > 0:
                return tracker.losses
            if tracker.total_losses > 0:
                return tracker.total_losses
            if tracker.games > 0:
                wins = tracker.total_wins if tracker.total_wins > 0 else (lzt.total_wins if lzt else 0)
                return max(tracker.games - wins, 0)
        return 0

    def _count_cards_with_level(
        self,
        cards: dict[str, dict[str, Any]],
        normalized_level: int,
    ) -> int:
        count = 0
        for card in cards.values():
            if not isinstance(card, dict):
                continue
            if self._to_int(card.get("normalizedLevel")) == normalized_level:
                count += 1
        return count

    def _count_evolutions(self, cards: dict[str, dict[str, Any]]) -> int:
        count = 0
        for card in cards.values():
            if not isinstance(card, dict):
                continue
            if self._to_int(card.get("evolutionLevel")) > 0:
                count += 1
        return count

    def _elite_card_names(self, cards: dict[str, dict[str, Any]]) -> list[str]:
        elite_cards: list[str] = []
        for card in cards.values():
            if not isinstance(card, dict):
                continue
            if self._to_int(card.get("normalizedLevel")) != 15:
                continue
            name = str(card.get("name") or "").strip()
            if name:
                elite_cards.append(name)
        return elite_cards

    def _to_int(self, value: Any) -> int:
        try:
            if value in (None, ""):
                return 0
            return int(value)
        except (TypeError, ValueError):
            return 0
