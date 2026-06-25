"""Eldorado builder for resolved Roblox accounts."""

from __future__ import annotations

from ..models import RobloxResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class RobloxEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Roblox account slice."""

    def build_payload(
        self,
        account: RobloxResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="70",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            attributes={
                "roblox-account-type": self._resolve_account_type(account),
                "roblox-game": "game-other",
                "roblox-inventory-value": self._resolve_inventory_value(account.inventory_price),
                "roblox-offsale-items": self._resolve_offsale(account.offsale_count),
                "roblox-robux-value": self._resolve_robux(account.robux),
                "roblox-verified": "verified-yes" if account.age_verified else "verified-no",
            },
            ref_key=account.ref_key,
        )

    # ── attribute resolvers ──────────────────────────────────────

    @staticmethod
    def _resolve_account_type(account: RobloxResolvedAccount) -> str:
        username_len = len(account.username) if account.username else 0
        if username_len == 4:
            return "type-4-letter"
        if account.inventory_price >= 10000:
            return "type-inventory"
        if account.offsale_count >= 50:
            return "type-offsale"
        if account.robux >= 1000:
            return "type-robux-account"
        return "type-other"

    @staticmethod
    def _resolve_inventory_value(value: float) -> str:
        if value < 1000:
            return "value-0999"
        if value < 2000:
            return "value-1199"
        if value < 5000:
            return "value-2499"
        if value < 10000:
            return "value-5999"
        if value < 15000:
            return "value-101499"
        if value < 20000:
            return "value-151999"
        if value < 30000:
            return "value-202999"
        if value < 50000:
            return "value-304999"
        if value < 100000:
            return "value-50999"
        return "value-100plus"

    @staticmethod
    def _resolve_offsale(count: int) -> str:
        if count < 10:
            return "offsale-09"
        if count < 50:
            return "offsale-1049"
        if count < 100:
            return "offsale-5099"
        if count < 200:
            return "offsale-100199"
        return "offsale-200plus"

    @staticmethod
    def _resolve_robux(robux: int) -> str:
        if robux < 1000:
            return "robux-0999"
        if robux < 2000:
            return "robux-1199"
        if robux < 5000:
            return "robux-2499"
        if robux < 10000:
            return "robux-5999"
        if robux < 15000:
            return "robux-101499"
        if robux < 20000:
            return "robux-151999"
        if robux < 30000:
            return "robux-202999"
        if robux < 50000:
            return "robux-304999"
        if robux < 100000:
            return "robux-5099"
        return "robux-100plus"
