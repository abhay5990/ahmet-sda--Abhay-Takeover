"""Resolve Genshin Impact account data from prepared sources."""

from __future__ import annotations

from .models import GenshinResolvedAccount
from .sources import GenshinLztSourceAdapter, GiManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class GenshinResolver:
    """Multi-source resolver for Genshin Impact / miHoYo (LZT + manual)."""

    def __init__(self) -> None:
        self._lzt = GenshinLztSourceAdapter()
        self._manual = GiManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> GenshinResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        lzt = self._lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Genshin Impact requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(self, manual, request: PipelineRequest) -> GenshinResolvedAccount:
        credentials = resolve_credentials(manual, kind=request.kind, game_name="Genshin Impact")

        return GenshinResolvedAccount(
            item_id=manual.item_id,
            category_id=manual.category_id,
            price=manual.price,
            kind=request.kind,
            credentials=credentials,
            region=manual.region,
            has_email_access=not manual.credentials.is_empty and bool(manual.credentials.email_login),
            manual_title=manual.title,
            manual_description=manual.description,
            # Integer counts from manual entry
            adventure_rank_level=manual.adventure_rank,
            genshin_level=manual.adventure_rank,
            character_count=manual.characters,
            genshin_character_count=manual.characters,
            legendary_weapon_count=manual.legendary_weapons,
            genshin_legendary_weapons=manual.legendary_weapons,
            primogem_count=manual.primogems,
            genshin_currency=manual.primogems,
            events_count=manual.events_count,
            # Pass manual attribute slugs for marketplace builders
            account_type_attr=manual.account_type if manual.account_type != "other" else "",
        )

    def _resolve_lzt(self, lzt, request: PipelineRequest) -> GenshinResolvedAccount:
        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Genshin Impact")

        # Derive name lists from character details
        genshin_5star_names = [
            c.name for c in lzt.genshin_characters
            if c.rarity == 5 and c.name != "Traveler"
        ]
        genshin_5star_weapon_names: list[str] = []
        seen_weapons: set[str] = set()
        for c in lzt.genshin_characters:
            if c.weapon_rarity == 5 and c.weapon_name and c.weapon_name not in seen_weapons:
                genshin_5star_weapon_names.append(c.weapon_name)
                seen_weapons.add(c.weapon_name)

        honkai_5star_names = [
            c.name for c in lzt.honkai_characters
            if c.rarity == 5 and c.name != "Trailblazer"
        ]

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
            genshin_characters=lzt.genshin_characters,
            honkai_characters=lzt.honkai_characters,
            zenless_characters=lzt.zenless_characters,
            genshin_5star_names=genshin_5star_names,
            genshin_5star_weapon_names=genshin_5star_weapon_names,
            honkai_5star_names=honkai_5star_names,
        )
