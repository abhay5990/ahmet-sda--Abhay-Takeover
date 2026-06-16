"""GameBoost builder for resolved Forza Horizon 5 accounts.

Template reference: ``assets/gameboost_templates/accounts/forza-horizon-5.json``
  - game slug: forza-horizon-5
  - account_data: platforms (array), edition, cars_count, credits_count
"""

from __future__ import annotations

from typing import Any

from ..models import Fh5ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.gameboost import BaseGameBoostBuilder


class Fh5GameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Forza Horizon 5 account slice."""

    @property
    def game_slug(self) -> str:
        return "forza-horizon-5"

    def _build_account_data(
        self, account: Fh5ResolvedAccount, ctx: BuildContext | None = None,
    ) -> dict[str, Any]:
        # GB expects platforms as an array
        gb_platform = get_external_id(
            ctx.variant_context if ctx else None, "platform", account.platform,
        ) or account.platform

        data: dict[str, Any] = {
            "edition": account.edition or "Standard",
        }
        if gb_platform:
            data["platforms"] = [gb_platform]
        if account.cars_count:
            data["cars_count"] = account.cars_count
        if account.credits_count:
            data["credits_count"] = account.credits_count
        return data
