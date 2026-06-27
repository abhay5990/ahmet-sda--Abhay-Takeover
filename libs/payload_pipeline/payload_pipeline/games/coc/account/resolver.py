"""Resolve Clash of Clans account data from multiple prepared sources."""

from __future__ import annotations

from .models import CocResolvedAccount
from .sources import CocLztSourceAdapter, CocManualSourceAdapter, CocTrackerSourceAdapter
from .sources.lzt import CocLztSource
from .sources.tracker import CocTrackerSource
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class CocResolver:
    """Multi-source resolver for Clash of Clans.

    Merge strategy:
    - Manual source takes priority when present
    - Credentials: LZT preferred, tracker fallback
    - Stats (TH, trophies, heroes): tracker preferred (more up-to-date), LZT fallback
    - Metadata (price, item_id, category_id): always from LZT
    """

    def __init__(self) -> None:
        self._lzt = CocLztSourceAdapter()
        self._tracker = CocTrackerSourceAdapter()
        self._manual = CocManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> CocResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT + tracker
        lzt = self._lzt.parse(request.source("lzt"))
        tracker = self._tracker.parse(request.source("tracker"))

        if lzt is None and tracker is None:
            raise SourceValidationError(
                "Clash of Clans requires at least one source: 'manual', 'lzt', or 'tracker'."
            )

        return self._resolve_lzt(lzt, tracker, request)

    def _resolve_manual(self, manual, request: PipelineRequest) -> CocResolvedAccount:
        credentials = resolve_credentials(manual, kind=request.kind, game_name="Clash of Clans")

        return CocResolvedAccount(
            item_id=manual.item_id,
            category_id=manual.category_id,
            price=manual.price,
            kind=request.kind,
            credentials=credentials,
            has_email_access=not manual.credentials.is_empty and bool(manual.credentials.email_login),
            manual_title=manual.title,
            manual_description=manual.description,
            # Categorical slugs (stays as select)
            current_rank_attr=manual.current_rank if manual.current_rank != "other" else "",
            maxed_account_attr=manual.maxed_account if manual.maxed_account != "other" else "",
            # Integer counts — Eldorado builder resolves these to slugs
            town_hall_level=manual.town_hall,
            gems_count=manual.gems,
        )

    def _resolve_lzt(
        self,
        lzt: CocLztSource | None,
        tracker: CocTrackerSource | None,
        request: PipelineRequest,
    ) -> CocResolvedAccount:
        credentials = self._resolve_credentials(request.kind, lzt, tracker)

        # Stats: tracker preferred when available
        town_hall_level = self._prefer_tracker_int(
            tracker.town_hall_level if tracker else 0,
            lzt.town_hall_level if lzt else 0,
        )
        builder_hall_level = self._prefer_tracker_int(
            tracker.builder_hall_level if tracker else 0,
            lzt.builder_hall_level if lzt else 0,
        )
        account_level = self._prefer_tracker_int(
            tracker.account_level if tracker else 0,
            lzt.account_level if lzt else 0,
        )
        trophies = self._prefer_tracker_int(
            tracker.trophies if tracker else 0,
            lzt.trophies if lzt else 0,
        )
        best_trophies = self._prefer_tracker_int(
            tracker.best_trophies if tracker else 0,
            lzt.best_trophies if lzt else 0,
        )
        war_stars = self._prefer_tracker_int(
            tracker.war_stars if tracker else 0,
            lzt.war_stars if lzt else 0,
        )

        # Heroes: tracker has individual hero levels, LZT only has BK + totals
        barbarian_king = self._prefer_tracker_int(
            tracker.barbarian_king_level if tracker else 0,
            lzt.barbarian_king_level if lzt else 0,
        )
        archer_queen = tracker.archer_queen_level if tracker else (lzt.archer_queen_level if lzt else 0)
        grand_warden = tracker.grand_warden_level if tracker else (lzt.grand_warden_level if lzt else 0)
        royal_champion = tracker.royal_champion_level if tracker else (lzt.royal_champion_level if lzt else 0)

        # Player tag: tracker preferred
        player_tag = ""
        if tracker and tracker.player_tag:
            player_tag = tracker.player_tag
        elif lzt and lzt.player_tag:
            player_tag = lzt.player_tag

        return CocResolvedAccount(
            item_id=lzt.item_id if lzt else "",
            category_id=lzt.category_id if lzt else 1,
            price=lzt.price if lzt else 0.0,
            kind=request.kind,
            credentials=credentials,
            town_hall_level=town_hall_level,
            builder_hall_level=builder_hall_level,
            account_level=account_level,
            trophies=trophies,
            best_trophies=best_trophies,
            war_stars=war_stars,
            barbarian_king_level=barbarian_king,
            archer_queen_level=archer_queen,
            grand_warden_level=grand_warden,
            royal_champion_level=royal_champion,
            total_heroes_level=lzt.total_heroes_level if lzt else 0,
            total_troops_level=lzt.total_troops_level if lzt else 0,
            total_spells_level=lzt.total_spells_level if lzt else 0,
            total_builder_heroes_level=lzt.total_builder_heroes_level if lzt else 0,
            total_builder_troops_level=lzt.total_builder_troops_level if lzt else 0,
            creation_year=lzt.creation_year if lzt else 0,
            has_phone=lzt.has_phone if lzt else False,
            battle_pass_active=lzt.battle_pass_active if lzt else False,
            heroes=tracker.heroes if tracker else [],
            troops=tracker.troops if tracker else [],
            spells=tracker.spells if tracker else [],
            hero_equipment=tracker.hero_equipment if tracker else [],
            super_troops=tracker.super_troops if tracker else [],
            player_tag=player_tag,
            has_email_access=self._resolve_has_email(lzt, tracker),
        )

    def _resolve_credentials(self, kind, lzt, tracker):
        return resolve_credentials(lzt, tracker, kind=kind, game_name="Clash of Clans")

    def _resolve_has_email(
        self,
        lzt: CocLztSource | None,
        tracker: CocTrackerSource | None,
    ) -> bool:
        if lzt and not lzt.credentials.is_empty and lzt.credentials.email_login:
            return True
        if tracker and not tracker.credentials.is_empty and tracker.credentials.email_login:
            return True
        return False

    def _prefer_tracker_int(self, tracker_val: int, lzt_val: int) -> int:
        """Use tracker value when positive, fall back to LZT."""
        return tracker_val if tracker_val > 0 else lzt_val
