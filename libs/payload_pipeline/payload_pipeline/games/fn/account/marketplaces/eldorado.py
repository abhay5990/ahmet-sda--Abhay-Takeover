"""Eldorado builder for resolved Fortnite accounts."""

from __future__ import annotations

import logging

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


def _available_platforms(config: EldoradoConfig) -> list[dict]:
    """Return platforms that still have available slots."""
    status = config.subplatform_status
    if not isinstance(status, dict):
        return []
    return [
        {"platform": k, "available": v.get("available", 0), "pct": v.get("percentage_used", 100.0)}
        for k, v in status.items()
        if isinstance(v, dict) and v.get("available", 0) > 0
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

        from .....core.enums import ListingKind

        if ctx.kind == ListingKind.STOCK:
            return self._stock_platform(account, el_config)
        return self._dropship_platform(account, el_config)

    # ── Stock: PSN/Xbox/PC önce, dolunca Android/iOS/Switch ───

    @staticmethod
    def _stock_platform(
        account: FortniteResolvedAccount,
        config: EldoradoConfig,
    ) -> str:
        available = _available_platforms(config)

        # Birincil platformlar: linkability'e uygun olanları önce dene
        primary_order: list[tuple[str, str]] = []
        if account.psn_linkable:
            primary_order.append(("psn", "1"))
        if account.xbox_linkable:
            primary_order.append(("xbox", "2"))
        primary_order.append(("pc", "0"))

        for key, pid in primary_order:
            if any(p["platform"] == key for p in available):
                return pid

        # İkincil platformlar: Android/iOS/Switch — slot olan hangisiyse
        secondary = [p for p in available if p["platform"] in ("android", "ios", "switch")]
        if secondary:
            best = min(secondary, key=lambda x: x["pct"])
            return _PLATFORM_KEY_TO_ID[best["platform"]]

        # Hiç slot yoksa fallback
        if account.psn_linkable:
            return "1"
        if account.xbox_linkable:
            return "2"
        return "0"

    # ── Dropship: linkability + en boş platform ──────────────

    @staticmethod
    def _dropship_platform(
        account: FortniteResolvedAccount,
        config: EldoradoConfig,
    ) -> str:
        available = _available_platforms(config)
        if not available:
            if account.psn_linkable:
                return "1"
            if account.xbox_linkable:
                return "2"
            return "0"

        # Linkable platformları filtrele
        linkable: list[dict] = []
        if account.psn_linkable:
            linkable.extend(p for p in available if p["platform"] == "psn")
        if account.xbox_linkable:
            linkable.extend(p for p in available if p["platform"] == "xbox")

        # Linkable varsa en boş olanı seç
        candidates = linkable if linkable else available
        best = min(candidates, key=lambda x: x["pct"])
        return _PLATFORM_KEY_TO_ID.get(best["platform"], "0")

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
