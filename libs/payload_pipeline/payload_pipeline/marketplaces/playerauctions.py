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

import hashlib
import re
import string
import unicodedata
from abc import abstractmethod
from typing import Any

from ..core.contracts import BuildContext, CredentialBundle, ListingDraft
from ..core.enums import ListingKind
from .base import BasePayloadBuilder, _DROPSHIPPING_DELIVERY


# ---------------------------------------------------------------------------
# Text sanitizer — PA only accepts Latin characters
# ---------------------------------------------------------------------------

# Cyrillic → Latin transliteration map (visually similar characters)
_CYRILLIC_MAP: dict[str, str] = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
    'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
    'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch',
    'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya',
}

# Emoji regex — covers most emoji ranges
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001FA00-\U0001FAFF"  # symbols extended
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ
    "\U000025A0-\U000025FF"  # geometric shapes
    "\U00002600-\U000026FF"  # misc symbols
    "\U0000231A-\U0000231B"  # watch/hourglass
    "\U00002934-\U00002935"  # arrows
    "\U000023E9-\U000023F3"  # media controls
    "\U000023F8-\U000023FA"  # media controls
    "]+",
    flags=re.UNICODE,
)

_EMOJI_REPLACEMENT = "*"


def _sanitize_text(text: str) -> str:
    """Sanitize text for PlayerAuctions: Latin-only, no emoji.

    Steps:
        1. Replace emojis with a safe placeholder (*).
        2. Transliterate Cyrillic characters to Latin equivalents.
        3. Decompose accented characters via NFKD and keep ASCII base letters.
        4. Remove any remaining non-Latin characters.
    """
    if not text:
        return text

    # 1. Replace emojis
    text = _EMOJI_RE.sub(_EMOJI_REPLACEMENT, text)

    # 2. Transliterate Cyrillic
    result = []
    for ch in text:
        if ch in _CYRILLIC_MAP:
            result.append(_CYRILLIC_MAP[ch])
        else:
            result.append(ch)
    text = "".join(result)

    # 3. NFKD decomposition — accented → base letter + combining mark
    text = unicodedata.normalize("NFKD", text)

    # 4. Keep only ASCII printable + common whitespace + safe Latin-1 subset
    cleaned = []
    for ch in text:
        if ord(ch) <= 127:
            # ASCII — keep everything (letters, digits, punctuation, whitespace)
            if ch.isprintable() or ch in ('\n', '\r', '\t'):
                cleaned.append(ch)
        elif unicodedata.category(ch).startswith('M'):
            # Combining marks (from NFKD) — skip them (base letter already kept)
            continue
        # Non-ASCII that survived — drop silently
    text = "".join(cleaned)

    # Collapse multiple * in a row (from consecutive emojis)
    text = re.sub(r"\*{2,}", "*", text)

    return text


def _strip_url_schemes(text: str) -> str:
    """Remove ``https://`` and ``http://`` prefixes from all URLs in text."""
    return re.sub(r"https?://", "", text)


def _stable_index(seed: str, salt: str, length: int) -> int:
    digest = hashlib.sha256(f"{salt}|{seed}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % length


def _fake_owner_info(creds: CredentialBundle, seed: str) -> dict[str, str]:
    """Generate deterministic plausible owner info for the autoDelivery section."""
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
        "firstName": first_names[_stable_index(seed, "first", len(first_names))],
        "lastName": last_names[_stable_index(seed, "last", len(last_names))],
        "phone": "5555555555",
        "email": creds.email_login or "randomemail@outlook.com",
        "city": cities[_stable_index(seed, "city", len(cities))],
        "country": countries[_stable_index(seed, "country", len(countries))],
    }


def _fake_character_name(seed: str) -> str:
    first_names = [
        "James", "John", "Robert", "Michael", "David",
        "William", "Richard", "Joseph", "Thomas", "Charles",
    ]
    name = first_names[_stable_index(seed, "character-name", len(first_names))]
    suffix = 100 + _stable_index(seed, "character-suffix", 9900)
    return f"{name}{suffix}"


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
        content = listing.content_for(self.marketplace, ref_key=subject.ref_key)
        price = self._apply_pricing(subject.price, ctx)
        is_stock = ctx.kind == ListingKind.STOCK
        creds: CredentialBundle = subject.credentials

        server_ids = self._get_server_id(subject)
        server_id = int(server_ids[0]) if server_ids else 0

        delivery_instructions = _sanitize_text(
            self._format_delivery(subject) if is_stock
            else _DROPSHIPPING_DELIVERY
        )

        owner_seed = "|".join(
            [
                str(self.game_id),
                str(server_id),
                content.title,
                creds.login,
                creds.email_login,
            ]
        )
        owner_info = _fake_owner_info(creds, owner_seed)

        auto_delivery: dict[str, Any] = {
            "loginName": creds.login,
            "retypeLoginName": creds.login,
            "password": creds.password,
            "retypePassword": creds.password,
            "characterName": _fake_character_name(owner_seed),
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

        screenshot = listing.media.external_urls[0] if listing.media.external_urls else ""

        return {
            "offerId": None,
            "gameId": self.game_id,
            "serverId": server_id,
            "categoryId": server_id,
            "price": round(max(price, 0.01), 2),
            "freeInsurance": 7,
            "offerDuration": 30,
            "title": _sanitize_text(_strip_url_schemes(content.title)),
            "offerDesc": _sanitize_text(_strip_url_schemes(content.description)).replace("\n", "<br>"),
            "screenShot": screenshot,
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
        content = listing.content_for(self.marketplace, ref_key=subject.ref_key)
        price = self._apply_pricing(subject.price, ctx)
        is_stock = ctx.kind == ListingKind.STOCK

        payload: dict[str, Any] = {
            "game_name": self.game_name,
            "game_id": self.game_id,
            "title": _sanitize_text(_strip_url_schemes(content.title)),
            "description": _sanitize_text(_strip_url_schemes(content.description)),
            "price": round(max(price, 0.01), 2),
            "server": self._get_server(subject),
            "cover_image_url": self.cover_image_url,
            "image_urls": list(listing.media.external_urls) if listing.media.external_urls else [],
            "delivery_method": "instant" if is_stock else "manual",
            "delivery_instructions": _sanitize_text(
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
