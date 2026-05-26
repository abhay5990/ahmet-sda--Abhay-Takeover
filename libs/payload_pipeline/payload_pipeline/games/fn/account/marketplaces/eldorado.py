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
