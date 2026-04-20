"""Reusable PlayerAuctions base builder.

Extracts the boilerplate repeated across all 8 game-specific PlayerAuctions
builders: pricing, delivery formatting, and the static payload skeleton.
Game slices subclass and implement only the game-specific constants and
server/region mapping.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from ..core.contracts import BuildContext, ListingDraft
from ..core.enums import ListingKind
from .base import BasePayloadBuilder, _DROPSHIPPING_DELIVERY


class BasePlayerAuctionsBuilder(BasePayloadBuilder[Any]):
    """Common shape for PlayerAuctions account payloads.

    Subclasses **must** implement:
    * ``game_name`` — the PA game slug (e.g. ``"valorant"``).
    * ``game_id`` — the PA numeric game ID (e.g. ``8470``).
    * ``cover_image_url`` — CDN URL for the game cover image.
    * ``_get_server`` — game-specific server name list.

    Subclasses **may** override:
    * ``_get_server_id`` — server ID list, default ``None`` (omitted).
    * ``_format_delivery`` — credential formatting, default uses standard template.
    * ``_platform_name`` — label used in delivery instructions.
    """

    marketplace = "playerauctions"

    @property
    @abstractmethod
    def game_name(self) -> str:
        """PlayerAuctions game slug (e.g. ``"valorant"``)."""

    @property
    @abstractmethod
    def game_id(self) -> int:
        """PlayerAuctions numeric game ID."""

    @property
    @abstractmethod
    def cover_image_url(self) -> str:
        """CDN URL for the game cover image."""

    @abstractmethod
    def _get_server(self, subject: Any) -> list[str]:
        """Return the server name(s) for this account."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        content = listing.content_for(self.marketplace)
        price = self._apply_pricing(subject.price, ctx)
        is_stock = ctx.kind == ListingKind.STOCK

        payload: dict[str, Any] = {
            "game_name": self.game_name,
            "game_id": self.game_id,
            "title": content.title,
            "description": content.description,
            "price": round(max(price, 0.01), 2),
            "server": self._get_server(subject),
            "cover_image_url": self.cover_image_url,
            "image_urls": list(listing.media.external_urls) if listing.media.external_urls else [],
            "delivery_method": "instant" if is_stock else "manual",
            "delivery_instructions": (
                self._format_delivery(subject) if is_stock
                else _DROPSHIPPING_DELIVERY
            ),
        }

        server_id = self._get_server_id(subject)
        if server_id is not None:
            payload["server_id"] = server_id

        return payload

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _get_server_id(self, subject: Any) -> list[str] | None:
        """Return server ID list or ``None`` to omit from payload."""
        return None

    @property
    def _platform_name(self) -> str:
        """Label for credential lines (e.g. ``"Riot Account"``)."""
        return "Account"

    def _format_delivery(self, subject: Any) -> str:
        """Format delivery instructions from credentials."""
        return self._standard_delivery(subject.credentials, self._platform_name)

