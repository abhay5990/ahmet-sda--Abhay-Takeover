"""Resolve Brawl Stars account data from prepared sources."""

from __future__ import annotations

from .models import BSResolvedAccount
from .sources import BSLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class BSResolver:
    """Single-source resolver for Brawl Stars."""

    def __init__(self) -> None:
        self.lzt = BSLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> BSResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Brawl Stars requires the 'lzt' source.")

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
