"""Resolve Roblox account data from prepared sources."""

from __future__ import annotations

from .models import RobloxResolvedAccount
from .sources import RobloxLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class RobloxResolver:
    """Single-source resolver for Roblox."""

    def __init__(self) -> None:
        self.lzt = RobloxLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> RobloxResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Roblox requires the 'lzt' source.")

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
