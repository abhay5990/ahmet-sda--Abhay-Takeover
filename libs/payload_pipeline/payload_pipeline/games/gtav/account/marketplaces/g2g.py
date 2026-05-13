"""G2G builder for resolved GTA V accounts.

brand_id ``lgc_game_24333`` and the ``lgc_24333_platform`` collection are the
seller-wide G2G configuration shared by **all** games in this repo (Brawl Stars,
Valorant, Roblox, CS2, Fortnite, etc.).  They are not game-specific.

The platform dataset is fixed to ``Android`` (``lgc_24333_platform_26098``) as a
deterministic legacy fallback.  The old builder randomly chose between Android and
IOS; both are accepted by the G2G API for any game.
"""

from __future__ import annotations

from typing import Any

from ..credentials import format_platform_credentials
from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, CredentialBundle, ListingDraft
from .....marketplaces.base import _DISCLAIMER
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_24333"
# Deterministic legacy fallback: always use Android.
# Both Android and IOS are accepted by the G2G API for all games.
_PLATFORM_DATASET_ID = "lgc_24333_platform_26098"


class GtavG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the GTA V account slice."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    def _build_offer_attributes(
        self,
        subject: Any,
    ) -> list[dict[str, str]]:
        return [
            {
                "collection_id": "lgc_24333_platform",
                "dataset_id": _PLATFORM_DATASET_ID,
            }
        ]

    def build_payload(
        self,
        subject: GtavResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        payload = super().build_payload(subject, listing, ctx)
        # Override softpin with platform-aware credential data
        if self._include_softpin:
            payload["softpin_data"] = self._build_gtav_softpin(subject)
        return payload

    @staticmethod
    def _build_gtav_softpin(account: GtavResolvedAccount) -> str:
        """Platform-aware softpin: credential text as the CSV note field."""
        creds = account.credentials
        username = creds.login or ""
        password = creds.password if creds.password != "1" else "noneedpsswd"
        email = creds.email_login or "unknown@gmail.com"
        email_password = creds.email_password or "unknown"

        # Build platform-aware note with all credential fields
        note = format_platform_credentials(
            account.main_platform,
            creds,
            account.credential_extras,
            disclaimer=_DISCLAIMER,
        )

        return f'{username},{password},,,,,,,,{email},{email_password},"{note}"\r\n'
