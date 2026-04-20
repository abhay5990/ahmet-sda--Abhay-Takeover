"""Resolve Genshin Impact account data from prepared sources."""

from __future__ import annotations

from .models import GenshinResolvedAccount
from .sources import GenshinLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class GenshinResolver:
    """Single-source resolver for Genshin Impact / miHoYo."""

    def __init__(self) -> None:
        self.lzt = GenshinLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> GenshinResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Genshin Impact requires the 'lzt' source.")

        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Genshin Impact")

        return GenshinResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            region=lzt.region,
            genshin_level=lzt.genshin_level,
            genshin_character_count=lzt.genshin_character_count,
            genshin_legendary_characters=lzt.genshin_legendary_characters,
            genshin_constellations=lzt.genshin_constellations,
            genshin_legendary_weapons=lzt.genshin_legendary_weapons,
            genshin_achievement_count=lzt.genshin_achievement_count,
            genshin_abyss_progress=lzt.genshin_abyss_progress,
            genshin_activity_days=lzt.genshin_activity_days,
            genshin_currency=lzt.genshin_currency,
            honkai_level=lzt.honkai_level,
            honkai_character_count=lzt.honkai_character_count,
            honkai_legendary_characters=lzt.honkai_legendary_characters,
            honkai_eidolons=lzt.honkai_eidolons,
            honkai_legendary_weapons=lzt.honkai_legendary_weapons,
            honkai_achievement_count=lzt.honkai_achievement_count,
            honkai_abyss_progress=lzt.honkai_abyss_progress,
            honkai_activity_days=lzt.honkai_activity_days,
            honkai_currency=lzt.honkai_currency,
            zenless_level=lzt.zenless_level,
            zenless_character_count=lzt.zenless_character_count,
            zenless_legendary_characters=lzt.zenless_legendary_characters,
            zenless_cinemas=lzt.zenless_cinemas,
            zenless_achievement_count=lzt.zenless_achievement_count,
            zenless_abyss_progress=lzt.zenless_abyss_progress,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
        )
