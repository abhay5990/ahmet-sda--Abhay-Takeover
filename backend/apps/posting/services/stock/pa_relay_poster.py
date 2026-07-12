"""PA Relay Poster — posts PA offers via the relay's /pa-post-offer endpoint.

Replaces the XLSX bulk-upload approach. The relay handles browser sessions,
cookies, and Cloudflare internally. We only need to:
  1. Get a JWT from /pa-access-token (already done by PlayerAuctionsAuth)
  2. POST the JSON offer payload to /pa-post-offer with that JWT as `cookie`

This module is responsible for:
- Building the JSON payload from the Excel row dict (which the pipeline already builds)
- Calling the relay /pa-post-offer endpoint
- Returning per-item results (offer_id on success, error on failure)
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from base64 import b64encode
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import requests
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PA RSA public key for password encryption (same as code-tracker)
# ---------------------------------------------------------------------------
_PA_RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0hnNIIDBLreG3t1lKWWZBxkZ+
rhRUtRJDC1kj96I12HuBabjmQPXAZKwSTC5R+sK0zkQ7gKAvKisFvCwNg7bokdLR
b/i/Et3GR6XTMBxZo1tLxiMp14SYDE0Q3+B/oKEFibXEiRwUiBywfDu/ps/Xmf5w
QgoMiP1ErP1ik4MSBQIDAQAB
-----END PUBLIC KEY-----"""

# ---------------------------------------------------------------------------
# PA Game IDs (from code-tracker PA_GAME_IDS)
# ---------------------------------------------------------------------------
PA_GAME_IDS: dict[str, int] = {
    "fortnite": 7876,
    "valorant": 9078,
    "league-of-legends": 3637,
    "rainbow-six-siege": 7773,
    "clash-of-clans": 1073,
    "clash-royale": 7293,
    "brawl-stars": 8463,
    "roblox": 5204,
    "minecraft": 4173,
}

# ---------------------------------------------------------------------------
# PA Server IDs per game (from code-tracker buildPlayerAuctionsServer)
# ---------------------------------------------------------------------------
PA_DEFAULT_SERVER_IDS: dict[str, Any] = {
    "fortnite": 7877,           # PC default
    "valorant": 9309,           # APAC default
    "league-of-legends": 4143,  # EU West default
    "rainbow-six-siege": 7774,  # PC default
    "clash-of-clans": 1234,     # Android
    "clash-royale": "Main Server",
    "brawl-stars": "Main Server",
    "minecraft": 4174,
    "roblox": 5205,             # Tax Covered
}

# ---------------------------------------------------------------------------
# Relay config
# ---------------------------------------------------------------------------
RELAY_URL = "http://35.231.166.148:3001"
RELAY_SECRET = "pa-relay-secret-2026"
RELAY_TIMEOUT = 60  # seconds

# ---------------------------------------------------------------------------
# Token fetch helper — gets a fresh PA JWT from the relay
# ---------------------------------------------------------------------------
def fetch_relay_token(
    username: str,
    password: str,
    store_slug: str,
    *,
    relay_url: str = RELAY_URL,
    relay_secret: str = RELAY_SECRET,
    timeout: int = 240,
) -> str | None:
    """Fetch a PA access token from the relay /pa-access-token endpoint.

    Uses cache-first: returns cached token instantly if relay warmup ran,
    otherwise triggers a fresh AdsPower browser login (up to 4 min).

    Returns:
        JWT token string on success, None on failure.
    """
    try:
        resp = requests.post(
            f"{relay_url}/pa-access-token",
            json={"username": username, "password": password, "store": store_slug},
            headers={
                "Content-Type": "application/json",
                "X-Relay-Secret": relay_secret,
            },
            timeout=timeout,
        )
        data = resp.json()
        if data.get("ok") and data.get("token"):
            logger.info(
                "PA relay token fetched for store=%s (cached=%s)",
                store_slug, data.get("cached", False),
            )
            return data["token"]
        logger.warning(
            "PA relay /pa-access-token returned ok=False for store=%s: %s",
            store_slug, data.get("error", "unknown"),
        )
        return None
    except requests.exceptions.Timeout:
        logger.error("PA relay /pa-access-token timeout for store=%s", store_slug)
        return None
    except Exception as exc:
        logger.error("PA relay /pa-access-token error for store=%s: %s", store_slug, exc)
        return None



@dataclass
class PARelayPostResult:
    """Per-item posting result."""
    successful: dict[int, str] = field(default_factory=dict)  # idx → offer_id
    failed: dict[int, str] = field(default_factory=dict)       # idx → error_msg


class PARelayPoster:
    """Posts PA offers via the relay's /pa-post-offer endpoint.

    Usage:
        poster = PARelayPoster()
        result = poster.post_batch(token, store_slug, rows)
        # result.successful = {0: "12345678"}
        # result.failed     = {1: "Please select a game."}
    """

    def post_batch(
        self,
        token: str,
        store_slug: str,
        rows: list[dict[str, Any]],
    ) -> PARelayPostResult:
        """Post each row as a separate JSON offer via the relay.

        Args:
            token:      JWT from /pa-access-token (used as both token and cookie)
            store_slug: "ezsmurfmart" or "ezsmurfshop"
            rows:       List of Excel row dicts (same format as XLSX uploader)
        """
        result = PARelayPostResult()

        for idx, row in enumerate(rows):
            try:
                payload = self._build_json_payload(row)
                offer_id, error = self._post_one(token, store_slug, payload)
                if offer_id:
                    result.successful[idx] = offer_id
                else:
                    result.failed[idx] = error or "Unknown PA relay error"
            except Exception as exc:
                logger.exception("PA relay post error for row %d", idx)
                result.failed[idx] = str(exc)

        logger.info(
            "PA relay batch done: %d successful, %d failed",
            len(result.successful), len(result.failed),
        )
        return result

    # ------------------------------------------------------------------
    # Internal: post one offer via relay
    # ------------------------------------------------------------------

    def _post_one(
        self,
        token: str,
        store_slug: str,
        payload: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """POST one offer to relay. Returns (offer_id, None) or (None, error)."""
        body = {
            "token": token,
            "cookie": token,   # relay uses this as Production_access_token cookie
            "store": store_slug,
            "payload": payload,
        }
        try:
            resp = requests.post(
                f"{RELAY_URL}/pa-post-offer",
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Relay-Secret": RELAY_SECRET,
                },
                timeout=RELAY_TIMEOUT,
            )
            data = resp.json()
        except requests.exceptions.Timeout:
            return None, "PA relay timeout"
        except Exception as exc:
            return None, f"PA relay connection error: {exc}"

        if data.get("ok"):
            offer_id = str(data.get("offerId", ""))
            return offer_id, None

        error = data.get("error") or f"HTTP {resp.status_code}"
        logger.warning("PA relay post failed: store=%s error=%r status=%s", self._store_slug if hasattr(self, '_store_slug') else '?', error, data.get('status'))
        return None, error

    # ------------------------------------------------------------------
    # Internal: build JSON payload from Excel row dict
    # ------------------------------------------------------------------

    def _build_json_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """Convert an Excel row dict to the PA JSON offer payload.

        Maps the XLSX column names to the JSON fields expected by /pa-post-offer.
        """
        game_name = str(row.get("Game", "")).lower().replace(" ", "-")
        game_id = PA_GAME_IDS.get(game_name, 0)
        server_id = self._get_server_id(row, game_name)

        price = float(row.get("Listing Price", 5.0))
        price = max(round(price * 100) / 100, 5.0)  # PA minimum $5

        title = pa_sanitize(str(row.get("Title", "")))[:150]
        description = pa_sanitize(str(row.get("Description", "")))[:3000].replace("\n", "<br>")

        login = str(row.get("Login name  (Auto)", "") or row.get("Login name", "") or "")
        password_plain = str(row.get("Password", "") or "")
        encrypted_password = pa_encrypt(password_plain)

        # Generate deterministic character name
        owner_seed = f"{game_id}|{server_id}|{title}|{login}"
        char_hash = hashlib.sha256(f"character-name|{owner_seed}".encode()).hexdigest()
        char_names = ["James", "John", "Robert", "Michael", "David", "William",
                      "Richard", "Joseph", "Thomas", "Charles"]
        character_name = (
            char_names[int(char_hash[:8], 16) % len(char_names)]
            + str(100 + int(char_hash[8:12], 16) % 9900)
        )

        # Generate deterministic owner info
        owner_info = pa_fake_owner_info(owner_seed)

        delivery_instructions = str(row.get("Delivery info", "") or row.get("Extra information", "") or "")
        delivery_instructions = pa_sanitize(delivery_instructions)

        auto_delivery = {
            "loginName": login,
            "retypeLoginName": login,
            "password": encrypted_password,
            "retypePassword": encrypted_password,
            "characterName": character_name,
            "isInfoSame": True,
            "original": owner_info,
            "current": dict(owner_info),
            "choose5": True,
            "instruction": delivery_instructions,
            "securityQuestion": str(row.get("Security question", "") or ""),
            "securityAnswer": str(row.get("Security question answer", "") or ""),
            "retypeSecurityAnswer": str(row.get("Security question answer", "") or ""),
            "parentalPassword": str(row.get("Parental password", "") or ""),
            "firstCDKey": str(row.get("Registration CD Key", "") or ""),
        }

        return {
            "offerId": None,
            "gameId": game_id,
            "serverId": server_id,
            "categoryId": server_id,
            "price": price,
            "freeInsurance": int(row.get("Seller After-Sale Protection", 7)),
            "offerDuration": int(row.get("Offer Duration", 30)),
            "title": title,
            "offerDesc": description,
            "screenShot": str(row.get("Cover image (PA hosted)", "") or ""),
            "agreeCheck": True,
            "isAuto": True,
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

    def _get_server_id(self, row: dict[str, Any], game_name: str) -> Any:
        """Resolve server ID from row Server field or game default.

        If the Server field is a numeric string, use it directly.
        Otherwise fall back to the game's default server ID.
        Named server strings (e.g. 'Main Server', 'PC') are only used
        for games where the default is already a string.
        """
        server_str = str(row.get("Server", "") or "").strip()
        default = PA_DEFAULT_SERVER_IDS.get(game_name, "PC")

        # If it's a numeric string, convert to int and use it
        if server_str and re.match(r"^\d+$", server_str):
            return int(server_str)

        # For games with string server IDs (Clash Royale, Brawl Stars), use the string
        if isinstance(default, str):
            return server_str if server_str else default

        # For games with numeric server IDs, always use the numeric default
        return default


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def pa_encrypt(plaintext: str) -> str:
    """RSA-encrypt a password for PA autoDelivery fields."""
    if not plaintext:
        return ""
    try:
        key = RSA.import_key(_PA_RSA_PUBLIC_KEY_PEM)
        cipher = PKCS1_v1_5.new(key)
        encrypted = cipher.encrypt(plaintext.encode("utf-8"))
        return b64encode(encrypted).decode("ascii")
    except Exception as exc:
        logger.warning("PA password encryption failed: %s", exc)
        return ""


def pa_fake_owner_info(seed: str) -> dict[str, str]:
    """Generate deterministic fake owner info for PA autoDelivery."""
    first_names = ["James", "John", "Robert", "Michael", "David", "William",
                   "Richard", "Joseph", "Thomas", "Charles"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                  "Miller", "Davis", "Rodriguez", "Martinez"]
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
              "San Antonio", "Dallas", "San Jose", "Austin", "Jacksonville"]
    countries = ["United States", "Canada", "United Kingdom", "Germany", "Australia"]

    def _hash(salt: str) -> int:
        h = hashlib.sha256(f"{salt}|{seed}".encode()).hexdigest()
        return int(h[:8], 16)

    return {
        "firstName": first_names[_hash("first") % len(first_names)],
        "lastName": last_names[_hash("last") % len(last_names)],
        "phone": "5555555555",
        "email": "randomemail@outlook.com",
        "city": cities[_hash("city") % len(cities)],
        "country": countries[_hash("country") % len(countries)],
    }


def pa_sanitize(text: str) -> str:
    """Sanitize text for PA — remove non-Latin chars, emojis, banned words."""
    if not text:
        return text

    # Remove https?:// from URLs
    text = re.sub(r"https?://", "", text)

    # Replace non-ASCII with *
    text = "".join(c if ord(c) < 128 else "*" for c in text)

    # Keep only ASCII printable + whitespace
    text = re.sub(r"[^\x20-\x7E\n\r\t]", "", text)

    # Collapse multiple *
    text = re.sub(r"\*{2,}", "*", text)

    # PA banned year patterns: 2018 → 20-18, 2013 → 20-13
    text = re.sub(r"\b(20)(18|13|16|17)\b", r"\1-\2", text)

    # PA banned standalone numbers (not part of larger numbers, not followed by x)
    text = re.sub(r"(?<!\d)13(?![\dx])", "1-3", text)
    text = re.sub(r"(?<!\d)18(?![\dx])", "1-8", text)

    # Remove banned words
    text = re.sub(r"\bvoice\s*chat\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bvoice\s*verified\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bvoice\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhack(ed|ing|s)?\b", "", text, flags=re.IGNORECASE)

    # Collapse extra whitespace
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r",\s*,", ",", text)
    return text.strip()
