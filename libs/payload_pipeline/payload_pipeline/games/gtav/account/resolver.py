"""Resolve GTA V account data from prepared sources."""

from __future__ import annotations

from .models import GtavResolvedAccount
from .sources import GtavManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class GtavResolver:
    """Single-source resolver for GTA V."""

    def __init__(self) -> None:
        self._adapter = GtavManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> GtavResolvedAccount:
        raw = request.source("manual") or request.source("lzt")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("GTA V requires the 'manual' or 'lzt' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="GTA V")

        return GtavResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
            main_platform=parsed.main_platform,
            level=parsed.level,
            cash_amount=parsed.cash_amount,
            cash_unit=parsed.cash_unit,
            cars_count=parsed.cars_count,
            tags=parsed.tags,
            has_dual_characters=parsed.has_dual_characters,
            security_email=parsed.security_email,
            security_email_password=parsed.security_email_password,
            security_email_login_link=parsed.security_email_login_link,
            birthday=parsed.birthday,
            email_backup_codes=parsed.email_backup_codes,
            has_email_access=not parsed.credentials.is_empty and bool(parsed.credentials.email_login),
            title=parsed.title,
            description=parsed.description,
        )
