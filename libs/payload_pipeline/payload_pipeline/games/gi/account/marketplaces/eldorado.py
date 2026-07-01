"""Eldorado builder for resolved Genshin Impact accounts."""

from __future__ import annotations

from typing import Any

from ..models import GenshinResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


class GenshinImpactEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado payload builder for the Genshin Impact account slice."""

    def build_payload(
        self,
        account: GenshinResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        trade_env = get_external_id(
            ctx.variant_context, "region", account.region_variant_key,
        ) or "1-999"

        return self.build_base_payload(
            game_id="39",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
            attributes={
                "genshin-account-type": account.account_type_attr or self._resolve_account_type(account),
                "genshin-adventure-rank": self._resolve_adventure_rank(account.genshin_level),
                "genshin-characters": self._resolve_characters(account.genshin_character_count),
                "genshin-events-count": self._resolve_events(account.events_count),
                "genshin-legendary-weapons": self._resolve_legendary_weapons(account.genshin_legendary_weapons),
                "genshin-primogems-count": self._resolve_primogems(account.genshin_currency),
            },
            ref_key=account.ref_key,
        )

    # ── attribute resolvers ──────────────────────────────────────

    @staticmethod
    def _resolve_account_type(account: GenshinResolvedAccount) -> str:
        if account.genshin_level <= 10 and account.genshin_legendary_characters >= 1:
            return "type-reroll"
        if account.genshin_legendary_characters >= 5:
            return "type-rolled"
        return "type-other"

    @staticmethod
    def _resolve_adventure_rank(level: int) -> str:
        if level <= 9:
            return "adventure-19"
        if level <= 44:
            return "adventure-1044"
        if level <= 49:
            return "adventure-4549"
        if level <= 59:
            return "adventure-5059"
        if level >= 60:
            return "adventure-60"
        return "adventure-other"

    @staticmethod
    def _resolve_characters(count: int) -> str:
        if count <= 39:
            return "characters-139"
        if count <= 49:
            return "characters-4049"
        if count <= 59:
            return "characters-5059"
        if count <= 69:
            return "characters-6069"
        if count <= 79:
            return "characters-7079"
        if count <= 89:
            return "characters-8089"
        if count >= 90:
            return "characters-90plus"
        return "characters-other"

    @staticmethod
    def _resolve_legendary_weapons(count: int) -> str:
        if count <= 3:
            return "legendary-03"
        if count <= 6:
            return "legendary-46"
        if count <= 9:
            return "legendary-79"
        if count >= 10:
            return "legendary-10plus"
        return "legendary-other"

    @staticmethod
    def _resolve_primogems(primogems: int) -> str:
        if primogems <= 9999:
            return "primogems-09k"
        if primogems <= 19999:
            return "primogems-1019k"
        if primogems <= 39999:
            return "primogems-2039k"
        if primogems <= 59999:
            return "primogems-4059k"
        return "primogems-60kplus"

    @staticmethod
    def _resolve_events(count: int) -> str:
        if count <= 4:
            return "events-04"
        if count <= 9:
            return "events-59"
        if count <= 14:
            return "events-1014"
        if count <= 19:
            return "events-1519"
        if count >= 20:
            return "events-20plus"
        return "events-other"
