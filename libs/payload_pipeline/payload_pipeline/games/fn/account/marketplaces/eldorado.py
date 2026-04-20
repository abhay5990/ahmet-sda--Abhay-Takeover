"""Eldorado builder for resolved Fortnite accounts."""

from __future__ import annotations

import logging
import random

from ..models import FortniteResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder, EldoradoConfig

logger = logging.getLogger(__name__)

_PLATFORM_NAME_TO_ID = {
    "PC": "0",
    "PlayStation": "1",
    "Xbox": "2",
    "Android": "3",
    "iOS": "4",
    "Switch": "5",
}

_PLATFORM_KEY_TO_ID = {
    "pc": "0",
    "psn": "1",
    "xbox": "2",
    "android": "3",
    "ios": "4",
    "switch": "5",
}

_SPECIAL_KEYWORDS = [
    "renegade", "ghoul", "skull", "aerial assault", "black knight",
    "travis scott", "galaxy", "reaper", "omega", "leviathan axe",
    "merry mint", "raider's revenge", "floss", "take the l",
]


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
            trade_environment_id=self._resolve_trade_environment_id(account, ctx),
            attributes={
                "fortnite-account-type": self._resolve_account_type(account),
            },
        )

    # ── trade environment (subplatform) ──────────────────────────

    def _resolve_trade_environment_id(
        self,
        account: FortniteResolvedAccount,
        ctx: BuildContext,
    ) -> str:
        el_config = ctx.get_config(EldoradoConfig)
        manual = el_config.current_subplatform
        if manual and manual != "Auto":
            return _PLATFORM_NAME_TO_ID.get(manual, "0")

        selected = self._select_best_subplatform(account, el_config)
        if selected is not None:
            return selected

        return self._fallback_platform(account)

    @staticmethod
    def _select_best_subplatform(
        account: FortniteResolvedAccount,
        config: EldoradoConfig,
    ) -> str | None:
        status = config.subplatform_status
        if not isinstance(status, dict):
            return None

        available = [
            {"platform": k, "available": v.get("available", 0), "pct": v.get("percentage_used", 100.0)}
            for k, v in status.items()
            if isinstance(v, dict) and v.get("available", 0) > 0
        ]
        if not available:
            return None

        linkable = [p for p in available if p["platform"] in ("psn", "xbox")]
        if linkable:
            if account.psn_linkable and any(p["platform"] == "psn" for p in linkable):
                best = min(linkable, key=lambda x: x["pct"])
                if best["platform"] == "psn":
                    return "1"
            if account.xbox_linkable and any(p["platform"] == "xbox" for p in linkable):
                best = min(linkable, key=lambda x: x["pct"])
                if best["platform"] == "xbox":
                    return "2"
                if best["platform"] == "psn" and account.psn_linkable:
                    return "1"

        best = min(available, key=lambda x: x["pct"])
        return _PLATFORM_KEY_TO_ID.get(best["platform"])

    @staticmethod
    def _fallback_platform(account: FortniteResolvedAccount) -> str:
        if account.psn_linkable:
            return "1"
        if account.xbox_linkable:
            return "2"
        return random.choice(["0", "1", "2", "3", "4", "5"])

    # ── attribute tier ───────────────────────────────────────────

    @staticmethod
    def _resolve_account_type(account: FortniteResolvedAccount) -> str:
        titles_lower = [t.lower() for t in account.cosmetic_titles]

        if any("rose team leader" in t for t in titles_lower):
            return "save-the-world"

        if account.level > 80:
            for t in titles_lower:
                for kw in _SPECIAL_KEYWORDS:
                    if kw in t:
                        return "og-account"

        return "stacked"
