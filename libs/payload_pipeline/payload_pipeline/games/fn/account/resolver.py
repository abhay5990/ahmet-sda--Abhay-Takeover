"""Resolve Fortnite account data from prepared sources."""

from __future__ import annotations

from .models import FortniteResolvedAccount
from .sources import FortniteLztSourceAdapter, FortniteManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class FortniteResolver:
    """Multi-source resolver for Fortnite (LZT + manual)."""

    def __init__(self) -> None:
        self._lzt = FortniteLztSourceAdapter()
        self._manual = FortniteManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> FortniteResolvedAccount:
        # Try manual source first (Google Sheet entries)
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        lzt = self._lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Fortnite requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(self, manual, request: PipelineRequest) -> FortniteResolvedAccount:
        credentials = resolve_credentials(manual, kind=request.kind, game_name="Fortnite")

        return FortniteResolvedAccount(
            item_id=manual.item_id,
            category_id=manual.category_id,
            price=manual.price,
            kind=request.kind,
            credentials=credentials,
            level=manual.level,
            platform=manual.platform,
            skin_count=manual.skin_count,
            pickaxe_count=manual.pickaxe_count,
            dance_count=manual.dance_count,
            glider_count=manual.glider_count,
            v_bucks=manual.v_bucks,
            lifetime_wins=manual.lifetime_wins,
            battle_pass_level=0,
            season_num=0,
            refund_credits=0,
            has_real_purchases=False,
            psn_linkable=manual.psn_linkable,
            xbox_linkable=manual.xbox_linkable,
            has_email_access=not manual.credentials.is_empty and bool(manual.credentials.email_login),
            fortnite_next_change_email_date=0,
            cosmetic_titles=[],
            cosmetics_by_category={},
            cosmetic_items={},
            preview_urls={},
            manual_title=manual.title,
            manual_description=manual.description,
            manual_images=manual.images,
            platforms=manual.platforms,
            backpack_count=manual.backpack_count,
            wrap_count=manual.wrap_count,
            banner_count=manual.banner_count,
            spray_count=manual.spray_count,
            exclusive_count=manual.exclusive_count,
        )

    def _resolve_lzt(self, lzt, request: PipelineRequest) -> FortniteResolvedAccount:
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
