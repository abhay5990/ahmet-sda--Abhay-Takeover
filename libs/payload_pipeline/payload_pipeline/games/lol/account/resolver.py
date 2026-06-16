"""Resolve League of Legends account data from prepared sources."""

from __future__ import annotations

from .catalog import skin_titles
from .models import LolResolvedAccount
from .sources import LolLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class LolResolver:
    """Single-source resolver for League of Legends."""

    def __init__(self) -> None:
        self.lzt = LolLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> LolResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("League of Legends requires the 'lzt' source.")

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
