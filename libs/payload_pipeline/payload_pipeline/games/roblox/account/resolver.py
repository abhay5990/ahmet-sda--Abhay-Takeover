"""Resolve Roblox account data from prepared sources."""

from __future__ import annotations

from .models import RobloxResolvedAccount
from .sources import RobloxLztSourceAdapter, RobloxManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class RobloxResolver:
    """Multi-source resolver for Roblox (LZT + manual)."""

    def __init__(self) -> None:
        self._lzt = RobloxLztSourceAdapter()
        self._manual = RobloxManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> RobloxResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        lzt = self._lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Roblox requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(self, manual, request: PipelineRequest) -> RobloxResolvedAccount:
        credentials = resolve_credentials(manual, kind=request.kind, game_name="Roblox")

        return RobloxResolvedAccount(
            item_id=manual.item_id,
            category_id=manual.category_id,
            price=manual.price,
            kind=request.kind,
            credentials=credentials,
            has_email_access=not manual.credentials.is_empty and bool(manual.credentials.email_login),
            manual_title=manual.title,
            manual_description=manual.description,
            # Integer counts from manual entry
            inventory_price=float(manual.inventory_value),
            offsale_count=manual.offsale_items,
            robux=manual.robux_value,
            # Pass manual attribute slugs for marketplace builders
            account_type_attr=manual.account_type if manual.account_type != "other" else "",
            game_attr=manual.game if manual.game != "other" else "",
            age_verified_attr=manual.age_verified if manual.age_verified != "other" else "",
        )

    def _resolve_lzt(self, lzt, request: PipelineRequest) -> RobloxResolvedAccount:
        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Roblox")

        return RobloxResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            roblox_id=lzt.roblox_id,
            robux=lzt.robux,
            incoming_robux_total=lzt.incoming_robux_total,
            inventory_price=lzt.inventory_price,
            ugc_limited_price=lzt.ugc_limited_price,
            limited_price=lzt.limited_price,
            offsale_count=lzt.offsale_count,
            friends=lzt.friends,
            followers=lzt.followers,
            age_verified=lzt.age_verified,
            email_verified=lzt.email_verified,
            verified=lzt.verified,
            register_date=lzt.register_date,
            country=lzt.country,
            has_subscription=lzt.has_subscription,
            voice_enabled=lzt.voice_enabled,
            xbox_connected=lzt.xbox_connected,
            psn_connected=lzt.psn_connected,
            username=lzt.username,
            game_pass_total_robux=lzt.game_pass_total_robux,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
        )
