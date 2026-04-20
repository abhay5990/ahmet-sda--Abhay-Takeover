"""Resolve GTA V account data from prepared sources."""

from __future__ import annotations

from .models import GtavResolvedAccount
from .sources import GtavLztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class GtavResolver:
    """Single-source resolver for GTA V."""

    def __init__(self) -> None:
        self.lzt = GtavLztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> GtavResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("GTA V requires the 'lzt' source.")

        credentials = resolve_credentials(lzt, kind=request.kind, game_name="GTA V")

        return GtavResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            main_platform=lzt.main_platform,
            level=lzt.level,
            cash_amount=lzt.cash_amount,
            cash_unit=lzt.cash_unit,
            cars_count=lzt.cars_count,
            tags=lzt.tags,
            security_email=lzt.security_email,
            security_email_password=lzt.security_email_password,
            security_email_login_link=lzt.security_email_login_link,
            birthday=lzt.birthday,
            email_backup_codes=lzt.email_backup_codes,
            eldorado_price=lzt.eldorado_price,
            gameboost_price=lzt.gameboost_price,
            playerauctions_price=lzt.playerauctions_price,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
            title=lzt.title,
            description=lzt.description,
        )
