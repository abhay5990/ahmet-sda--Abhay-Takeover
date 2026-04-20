"""Resolve Valorant account data from prepared sources."""

from __future__ import annotations

from .models import ValorantResolvedAccount
from .sources import ValorantLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class ValorantResolver:
    """Single-source resolver for Valorant account listings."""

    def __init__(self) -> None:
        self.lzt = ValorantLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> ValorantResolvedAccount:
        source = self.lzt.parse(request.source("lzt"))
        if source is None:
            raise SourceValidationError("Valorant requires the 'lzt' source.")

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
