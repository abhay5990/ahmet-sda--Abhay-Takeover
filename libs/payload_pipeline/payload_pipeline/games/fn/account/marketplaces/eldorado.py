"""Eldorado builder for resolved Fortnite accounts."""

from __future__ import annotations

from ..models import FortniteResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


class FortniteEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Fortnite account slice."""

    def build_payload(
        self,
        account: FortniteResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="16",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=self._resolve_trade_environment_id(ctx),
            attributes={
                "fortnite-account-type": self._resolve_account_type(account),
                "fortnite-emotes": self._resolve_cosmetic_bucket(account.dance_count, "emotes"),
                "fortnite-outfits-skins": self._resolve_cosmetic_bucket(account.skin_count, "outfits"),
                "fortnite-pickaxes": self._resolve_cosmetic_bucket(account.pickaxe_count, "pickaxes"),
                "fortnite-vbucks": self._resolve_vbucks(account.v_bucks),
            },
            ref_key=account.ref_key,
        )

    @staticmethod
    def _resolve_trade_environment_id(ctx: BuildContext) -> str:
        """Map selected platform variant to Eldorado trade environment ID.

        Platform selection is handled by the backend VariantRouter; the
        pipeline only resolves the slug to the marketplace external ID.
        """
        selected = (ctx.selected_variants or {}).get("platform")
        return get_external_id(ctx.variant_context, "platform", selected) or "0"

    # ── attribute tier ───────────────────────────────────────────

    @staticmethod
    def _resolve_account_type(account: FortniteResolvedAccount) -> str:
        titles_lower = [t.lower() for t in account.cosmetic_titles]

        if any("rose team leader" in t for t in titles_lower):
            return "save-the-world"

        skin_count = len(account.cosmetic_titles)
        if account.level >= 600 and skin_count >= 200:
            return "stacked"

        return "og-account"

    @staticmethod
    def _resolve_cosmetic_bucket(count: int, prefix: str) -> str:
        if count <= 0:
            return f"{prefix}-other"
        if count <= 49:
            return f"{prefix}-149"
        if count <= 99:
            return f"{prefix}-5099"
        if count <= 199:
            return f"{prefix}-100199"
        if count <= 499:
            return f"{prefix}-200499"
        return f"{prefix}-500plus"

    @staticmethod
    def _resolve_vbucks(v_bucks: int) -> str:
        if v_bucks <= 0:
            return "vbucks-other"
        if v_bucks <= 499:
            return "vbucks-1499"
        if v_bucks <= 999:
            return "vbucks-500999"
        if v_bucks <= 1999:
            return "vbucks-1199"
        if v_bucks <= 4999:
            return "vbucks-2499"
        return "vbucks-5"
