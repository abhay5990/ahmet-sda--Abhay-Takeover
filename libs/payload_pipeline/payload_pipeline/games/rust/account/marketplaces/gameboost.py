"""GameBoost builder for resolved Rust accounts.

Template reference: ``assets/gameboost_templates/accounts/rust.json``
  - game slug: rust
  - account_data: platform, real_hours_count, skins_count, twitch_drops_count
"""

from __future__ import annotations

from typing import Any

from ..models import RustResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.gameboost import BaseGameBoostBuilder


class RustGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Rust account slice."""

    @property
    def game_slug(self) -> str:
        return "rust"

    def _build_account_data(
        self, account: RustResolvedAccount, ctx: BuildContext | None = None,
    ) -> dict[str, Any]:
        gb_platform = get_external_id(
            ctx.variant_context if ctx else None, "platform", account.platform,
        ) or account.platform

        data: dict[str, Any] = {}
        if gb_platform:
            data["platform"] = gb_platform
        if account.real_hours:
            data["real_hours_count"] = account.real_hours
        if account.skins_count:
            data["skins_count"] = account.skins_count
        return data
