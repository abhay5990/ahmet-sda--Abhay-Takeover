"""Resolve Valorant account data from prepared sources."""

from __future__ import annotations

from .models import ValorantResolvedAccount
from .sources import ValorantLztSourceAdapter, ValorantManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class ValorantResolver:
    """Multi-source resolver for Valorant (manual + LZT)."""

    def __init__(self) -> None:
        self._lzt = ValorantLztSourceAdapter()
        self._manual = ValorantManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> ValorantResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        source = self._lzt.parse(request.source("lzt"))
        if source is None:
            raise SourceValidationError("Valorant requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(source, request)

    def _resolve_manual(self, src, request: PipelineRequest) -> ValorantResolvedAccount:
        credentials = resolve_credentials(src, kind=request.kind, game_name="Valorant")
        current_rank = src.current_rank or "Unranked"
        rank_type = (
            "ranked"
            if current_rank.lower() not in {"", "unranked", "no rank", "ranked ready"}
            else "ranked_ready" if src.level >= 20 else ""
        )

        return ValorantResolvedAccount(
            item_id=src.item_id,
            category_id=src.category_id,
            price=src.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=src.title,
            manual_description=src.description,
            region=src.region,
            level=src.level,
            valorant_points=src.valorant_points,
            radianite_points=src.radianite_points,
            rank_type=rank_type,
            current_rank=current_rank,
            previous_rank=src.peak_rank or "No Rank",
            last_rank=src.peak_rank or "No Rank",
            skin_count=src.skin_count,
            agent_count=src.agent_count,
            knife_count=src.knife_count,
            inventory_value=src.inventory_value,
            account_tags=list(src.account_tags),
        )

    def _resolve_lzt(self, source, request: PipelineRequest) -> ValorantResolvedAccount:
        credentials = resolve_credentials(source, kind=request.kind, game_name="Valorant")

        return ValorantResolvedAccount(
            item_id=source.item_id,
            category_id=source.category_id,
            price=source.price,
            kind=request.kind,
            credentials=credentials,
            tracker_url=source.tracker_url,
            region=source.region,
            level=source.level,
            valorant_points=source.valorant_points,
            radianite_points=source.radianite_points,
            rank_type=source.rank_type,
            current_rank=source.current_rank,
            previous_rank=source.previous_rank,
            last_rank=source.last_rank,
            agent_names=list(source.agent_names),
            skin_names=list(source.skin_names),
            buddy_names=list(source.buddy_names),
            preview_urls=dict(source.preview_urls),
            skin_count=source.skin_count,
            agent_count=source.agent_count,
            buddy_count=source.buddy_count,
            knife_count=source.knife_count,
            inventory_value=source.inventory_value,
        )
