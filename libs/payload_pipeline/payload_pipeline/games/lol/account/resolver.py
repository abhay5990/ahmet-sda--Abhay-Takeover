"""Resolve League of Legends account data from prepared sources."""

from __future__ import annotations

from .catalog import skin_titles
from .models import LolResolvedAccount
from .sources import LolLztSourceAdapter, LolManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class LolResolver:
    """Multi-source resolver for League of Legends (manual + LZT)."""

    def __init__(self) -> None:
        self._lzt = LolLztSourceAdapter()
        self._manual = LolManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> LolResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        lzt = self._lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("League of Legends requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(self, src, request: PipelineRequest) -> LolResolvedAccount:
        credentials = resolve_credentials(src, kind=request.kind, game_name="League of Legends")

        return LolResolvedAccount(
            item_id=src.item_id,
            category_id=src.category_id,
            price=src.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=src.title,
            manual_description=src.description,
            region=src.server,
            has_email_access=not credentials.is_empty and bool(credentials.email_login),
            # Categorical slugs (stays as select)
            current_rank_attr=src.current_rank if src.current_rank != "other" else "",
            previous_rank_attr=src.previous_rank if src.previous_rank != "other" else "",
            ranked_ready_attr=src.ranked_ready if src.ranked_ready != "other" else "",
            # Integer counts — Eldorado builder resolves these to slugs
            champion_count=src.champion_count,
            skin_count=src.skins,
            blue_essence=src.blue_essence,
            riot_points=src.riot_points,
        )

    def _resolve_lzt(self, lzt, request: PipelineRequest) -> LolResolvedAccount:
        credentials = resolve_credentials(lzt, kind=request.kind, game_name="League of Legends")

        return LolResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            region=lzt.region,
            region_phrase=lzt.region_phrase,
            level=lzt.level,
            rank=lzt.rank,
            rank_win_rate=lzt.rank_win_rate,
            champion_count=lzt.champion_count,
            skin_count=lzt.skin_count,
            blue_essence=lzt.blue_essence,
            orange_essence=lzt.orange_essence,
            mythic_essence=lzt.mythic_essence,
            riot_points=lzt.riot_points,
            champion_ids=lzt.champion_ids,
            skin_ids=lzt.skin_ids,
            skin_names=skin_titles(lzt.skin_ids),
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
        )
