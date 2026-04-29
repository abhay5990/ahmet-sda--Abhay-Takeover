"""Resolve Fortnite account data from prepared sources."""

from __future__ import annotations

from .models import FortniteResolvedAccount
from .sources import FortniteLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class FortniteResolver:
    """Single-source resolver for Fortnite."""

    def __init__(self) -> None:
        self.lzt = FortniteLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> FortniteResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Fortnite requires the 'lzt' source.")

        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Fortnite")

        return FortniteResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            level=lzt.level,
            platform=lzt.platform,
            skin_count=lzt.skin_count,
            pickaxe_count=lzt.pickaxe_count,
            dance_count=lzt.dance_count,
            glider_count=lzt.glider_count,
            v_bucks=lzt.v_bucks,
            lifetime_wins=lzt.lifetime_wins,
            battle_pass_level=lzt.battle_pass_level,
            season_num=lzt.season_num,
            refund_credits=lzt.refund_credits,
            has_real_purchases=lzt.has_real_purchases,
            psn_linkable=lzt.psn_linkable,
            xbox_linkable=lzt.xbox_linkable,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
            fortnite_next_change_email_date=lzt.fortnite_next_change_email_date,
            cosmetic_titles=lzt.cosmetic_titles,
            cosmetics_by_category=lzt.cosmetics_by_category,
            cosmetic_items=lzt.cosmetic_items,
            preview_urls=lzt.preview_urls,
        )
