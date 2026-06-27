"""Resolve Steam account data from prepared sources."""

from __future__ import annotations

from .models import SteamResolvedAccount
from .sources import SteamLztSourceAdapter, SteamManualSourceAdapter
from .sources.lzt import SteamLztSource
from .sources.manual import SteamManualSource
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class SteamResolver:
    """Dual-source resolver for Steam (manual first, LZT fallback)."""

    def __init__(self) -> None:
        self._manual = SteamManualSourceAdapter()
        self.lzt = SteamLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> SteamResolvedAccount:
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("Steam requires the 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(
        self,
        src: SteamManualSource,
        request: PipelineRequest,
    ) -> SteamResolvedAccount:
        credentials = resolve_credentials(src, kind=request.kind, game_name="Steam")
        return SteamResolvedAccount(
            item_id=src.item_id,
            category_id=src.category_id,
            price=src.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=src.title,
            manual_description=src.description,
        )

    def _resolve_lzt(
        self,
        lzt: SteamLztSource,
        request: PipelineRequest,
    ) -> SteamResolvedAccount:
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
