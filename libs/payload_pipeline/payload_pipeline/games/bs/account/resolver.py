"""Resolve Brawl Stars account data from prepared sources."""

from __future__ import annotations

from .models import BSResolvedAccount
from .sources import BSLztSourceAdapter, BsManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class BSResolver:
    """Multi-source resolver for Brawl Stars (LZT + manual)."""

    def __init__(self) -> None:
        self._lzt = BSLztSourceAdapter()
        self._manual = BsManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> BSResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        lzt = self._lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Brawl Stars requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(self, manual, request: PipelineRequest) -> BSResolvedAccount:
        credentials = resolve_credentials(manual, kind=request.kind, game_name="Brawl Stars")

        return BSResolvedAccount(
            item_id=manual.item_id,
            category_id=manual.category_id,
            price=manual.price,
            kind=request.kind,
            credentials=credentials,
            has_email_access=not manual.credentials.is_empty and bool(manual.credentials.email_login),
            manual_title=manual.title,
            manual_description=manual.description,
            # Categorical slug (rank stays as select)
            rank_attr=manual.rank if manual.rank != "other" else "",
            # Integer counts — Eldorado builder resolves these to slugs
            trophies=manual.trophies,
            brawler_count=manual.brawlers,
            max_level_brawlers_count=manual.maxed_brawlers,
            hypercharge_count=manual.hypercharge,
            skin_count=manual.skins,
            prestige_count=manual.prestige,
            buffies_count=manual.buffies,
            gems_count=manual.gems,
        )

    def _resolve_lzt(self, lzt, request: PipelineRequest) -> BSResolvedAccount:
        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Brawl Stars")

        return BSResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            level=lzt.level,
            trophies=lzt.trophies,
            brawler_count=lzt.brawler_count,
            legendary_brawler_count=lzt.legendary_brawler_count,
            max_level_brawlers_count=lzt.max_level_brawlers_count,
            rank_30_plus_count=lzt.rank_30_plus_count,
            mythic_count=lzt.mythic_count,
            battle_pass_active=lzt.battle_pass_active,
            hypercharge_count=lzt.hypercharge_count,
            highest_trophies=lzt.highest_trophies,
            victories=lzt.victories,
            creation_year=lzt.creation_year,
            brawler_names=lzt.brawler_names,
            brawlers=lzt.brawlers,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
        )
