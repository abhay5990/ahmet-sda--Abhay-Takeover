"""Resolve Steam account data from prepared sources."""

from __future__ import annotations

from .models import SteamResolvedAccount
from .sources import SteamLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class SteamResolver:
    """Single-source resolver for Steam."""

    def __init__(self) -> None:
        self.lzt = SteamLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> SteamResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Steam requires the 'lzt' source.")

        credentials = resolve_credentials(lzt, kind=request.kind, game_name="Steam")

        return SteamResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            steam_id=lzt.steam_id,
            country=lzt.country,
            register_date=lzt.register_date,
            steam_level=lzt.steam_level,
            total_games=lzt.total_games,
            games=lzt.games,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
        )
