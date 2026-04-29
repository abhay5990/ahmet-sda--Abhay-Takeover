"""Reusable PlayerAuctions base builder.

Extracts the boilerplate repeated across all game-specific PlayerAuctions
builders: pricing, delivery formatting, and the static payload skeleton.
Game slices subclass and implement only the game-specific constants and
server/region mapping.

Two payload formats:

* ``build_payload``  — PA ``create_offer`` API JSON (single post).
  Passwords are **plain text**; encryption is the caller's responsibility
  (see ``PAPasswordEncryptor`` in ``apis_sdk``).
* ``build_bulk_payload`` — intermediate dict that feeds into Excel/bulk upload.
"""

from __future__ import annotations

import random
import string
from abc import abstractmethod
from typing import Any

from ..core.contracts import BuildContext, CredentialBundle, ListingDraft
from ..core.enums import ListingKind
from .base import BasePayloadBuilder, _DROPSHIPPING_DELIVERY


def _fake_owner_info(creds: CredentialBundle) -> dict[str, str]:
    """Generate plausible owner info for the autoDelivery section."""
    first_names = [
        "James", "John", "Robert", "Michael", "David",
        "William", "Richard", "Joseph", "Thomas", "Charles",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones",
        "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    ]
    cities = [
        "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
        "San Antonio", "Dallas", "San Jose", "Austin", "Jacksonville",
    ]
    countries = [
        "United States", "Canada", "United Kingdom",
        "Germany", "Australia",
    ]
    return {
        "firstName": random.choice(first_names),
        "lastName": random.choice(last_names),
        "phone": "5555555555",
        "email": creds.email_login or "randomemail@outlook.com",
        "city": random.choice(cities),
        "country": random.choice(countries),
    }


class BasePlayerAuctionsBuilder(BasePayloadBuilder[Any]):
    """Common shape for PlayerAuctions account payloads.

    Subclasses **must** implement:
    * ``game_name`` — the PA game slug (e.g. ``"valorant"``).
    * ``game_id`` — the PA numeric game ID (from template JSON).
    * ``cover_image_url`` — CDN URL for the game cover image.
    * ``_get_server`` — game-specific server name list.

    Subclasses **may** override:
    * ``_get_server_id`` — server ID list, default ``None`` (omitted).
    * ``_format_delivery`` — credential formatting, default uses standard template.
    * ``_platform_name`` — label used in delivery instructions.
    * ``requires_security_qa`` — whether PA requires security Q&A for this game.
    * ``requires_parental_password`` — whether PA requires parental password.
    """

    marketplace = "playerauctions"

    @property
    @abstractmethod
    def game_name(self) -> str:
        """PlayerAuctions game slug (e.g. ``"valorant"``)."""

    @property
    @abstractmethod
    def game_id(self) -> int:
        """PlayerAuctions numeric game ID (from template JSON)."""

    @property
    @abstractmethod
    def cover_image_url(self) -> str:
        """CDN URL for the game cover image."""

    @abstractmethod
    def _get_server(self, subject: Any) -> list[str]:
        """Return the server name(s) for this account."""

    # ------------------------------------------------------------------
    # Game-level flags (override per game from template requiredFields)
    # ------------------------------------------------------------------

    requires_security_qa: bool = False
    requires_parental_password: bool = False

    # ------------------------------------------------------------------
    # Public API — single post (create_offer)
    # ------------------------------------------------------------------

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        """Build PA ``create_offer`` API payload.

        Passwords are plain text.  The consuming layer must encrypt fields
        marked ``"encrypted": true`` in the PA template (password,
        parentalPassword, securityAnswer) before sending to the API.
        """
        content = listing.content_for(self.marketplace)
        price = self._apply_pricing(subject.price, ctx)
        is_stock = ctx.kind == ListingKind.STOCK
        creds: CredentialBundle = subject.credentials

        server_ids = self._get_server_id(subject)
        server_id = int(server_ids[0]) if server_ids else 0

        delivery_instructions = (
            self._format_delivery(subject) if is_stock
            else _DROPSHIPPING_DELIVERY
        )

        owner_info = _fake_owner_info(creds)

        auto_delivery: dict[str, Any] = {
            "loginName": creds.login,
            "retypeLoginName": creds.login,
            "password": creds.password,
            "retypePassword": creds.password,
            "characterName": f"{random.choice(['James', 'John', 'Robert', 'Michael', 'David', 'William', 'Richard', 'Joseph', 'Thomas', 'Charles'])}{random.randint(100, 9999)}",
            "isInfoSame": True,
            "original": owner_info,
            "current": dict(owner_info),
            "choose5": True,
            "instruction": delivery_instructions,
        }

        auto_delivery["securityQuestion"] = ""
        auto_delivery["securityAnswer"] = ""
        auto_delivery["retypeSecurityAnswer"] = ""

        auto_delivery["parentalPassword"] = ""

        auto_delivery["firstCDKey"] = ""

        return {
            "offerId": None,
            "gameId": self.game_id,
            "serverId": server_id,
            "categoryId": server_id,
            "price": round(max(price, 0.01), 2),
            "freeInsurance": 7,
            "offerDuration": 30,
            "title": content.title,
            "offerDesc": content.description.replace("\n", "<br>"),
            "screenShot": "",
            "agreeCheck": True,
            "isAuto": is_stock,
            "autoDelivery": auto_delivery,
            "manual": {
                "loginName": "",
                "retypeLoginName": "",
                "choose1": None,
                "choose2": None,
                "choose3": None,
                "choose4": None,
                "choose5": None,
                "deliveryGuarantee": 4,
            },
            "actionType": "",
        }

    # ------------------------------------------------------------------
    # Public API — bulk upload (Excel)
    # ------------------------------------------------------------------

    def build_bulk_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        """Build intermediate dict for PA bulk/Excel upload."""
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
