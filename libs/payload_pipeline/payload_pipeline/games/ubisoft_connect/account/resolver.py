"""Resolve Ubisoft Connect account data from prepared sources."""

from __future__ import annotations

from .models import UbisoftResolvedAccount
from .sources import UbisoftLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class UbisoftResolver:
    """Single-source resolver for Ubisoft Connect."""

    def __init__(self) -> None:
        self.lzt = UbisoftLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> UbisoftResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Ubisoft Connect requires the 'lzt' source.")

        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Ubisoft Connect")

        return UbisoftResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            uplay_id=lzt.uplay_id,
            country=lzt.country,
            created_date=lzt.created_date,
            game_count=lzt.game_count,
            games=lzt.games,
            has_subscription=lzt.has_subscription,
            subscription_end_date=lzt.subscription_end_date,
            xbox_connected=lzt.xbox_connected,
            psn_connected=lzt.psn_connected,
            balance=lzt.balance,
            converted_balance=lzt.converted_balance,
            r6_level=lzt.r6_level,
            r6_ban=lzt.r6_ban,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
        )
