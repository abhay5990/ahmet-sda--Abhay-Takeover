"""Platform-aware credential formatting for GTA V accounts.

Central module defining which credential fields appear, in what order,
and with what labels — based on the account's ``main_platform``.

Three platform families exist:

- **PSN** (PS4 / PS5): PSN ID, PSN Pass, Email chain, Security Email chain, DoB
- **Xbox** (One / Series X/S): Xbox ID, Xbox Pass, Email chain, Security Email chain
- **PC** (Legacy / Enhanced): Steam ID/Pass, Rock ID/Pass, Email chain, Security Email chain

Consumers:
    1. Pipeline marketplace builders (listing creation delivery text)
    2. Pool formatter (autorestock credential push)
    3. Source adapter (parsing incoming raw data)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ....core.contracts import CredentialBundle


@dataclass(frozen=True, slots=True)
class CredentialField:
    """Single credential field definition.

    Exactly one of ``credential_key`` or ``raw_data_key`` should be the
    primary source.  When both are set, ``raw_data_key`` is checked first
    and ``credential_key`` serves as fallback.
    """

    label: str
    raw_data_key: str | None = None
    credential_key: str | None = None


# ── Platform field specifications ─────────────────────────────────

_EMAIL_CHAIN: list[CredentialField] = [
    CredentialField("Email", credential_key="email_login"),
    CredentialField("Email Password", credential_key="email_password"),
    CredentialField("Email Login Link", credential_key="email_login_link"),
]

_SECURITY_EMAIL_CHAIN: list[CredentialField] = [
    CredentialField("Security Email", raw_data_key="security_email", credential_key="security_email"),
    CredentialField("Security Email Password", raw_data_key="security_email_password", credential_key="security_email_password"),
    CredentialField("Security Email Login Link", raw_data_key="security_email_login_link"),
]

PSN_FIELDS: list[CredentialField] = [
    CredentialField("PSN ID", raw_data_key="psn_id", credential_key="login"),
    CredentialField("PSN Password", raw_data_key="psn_pass", credential_key="password"),
    *_EMAIL_CHAIN,
    *_SECURITY_EMAIL_CHAIN,
    CredentialField("Date of Birth", raw_data_key="dob"),
]

XBOX_FIELDS: list[CredentialField] = [
    CredentialField("Xbox ID", raw_data_key="xbox_id", credential_key="login"),
    CredentialField("Xbox Password", raw_data_key="xbox_pass", credential_key="password"),
    *_EMAIL_CHAIN,
    *_SECURITY_EMAIL_CHAIN,
]

PC_FIELDS: list[CredentialField] = [
    CredentialField("Steam ID", raw_data_key="steam_id", credential_key="login"),
    CredentialField("Steam Password", raw_data_key="steam_pass", credential_key="password"),
    CredentialField("Rockstar ID", raw_data_key="rock_id"),
    CredentialField("Rockstar Password", raw_data_key="rock_pass"),
    *_EMAIL_CHAIN,
    *_SECURITY_EMAIL_CHAIN,
]

# Fallback for unknown platforms — generic labels, same as current behavior
DEFAULT_FIELDS: list[CredentialField] = [
    CredentialField("Login", credential_key="login"),
    CredentialField("Password", credential_key="password"),
    *_EMAIL_CHAIN,
    *_SECURITY_EMAIL_CHAIN,
    CredentialField("Date of Birth", raw_data_key="dob"),
]

PLATFORM_SPECS: dict[str, list[CredentialField]] = {
    "PlayStation 4": PSN_FIELDS,
    "PlayStation 5": PSN_FIELDS,
    "Xbox One": XBOX_FIELDS,
    "Xbox Series X/S": XBOX_FIELDS,
    "PC - Legacy": PC_FIELDS,
    "PC - Enhanced": PC_FIELDS,
}


# ── Public API ────────────────────────────────────────────────────


def resolve_platform_credentials(
    platform: str,
    credentials: CredentialBundle,
    raw_data: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Return ordered (label, value) pairs for the given platform.

    Values are resolved from *raw_data* first, falling back to
    *credentials* fields.  Empty values are omitted.
    """
    spec = PLATFORM_SPECS.get(platform, DEFAULT_FIELDS)
    raw = raw_data or {}
    pairs: list[tuple[str, str]] = []

    for f in spec:
        value = ""
        # raw_data takes priority
        if f.raw_data_key:
            value = str(raw.get(f.raw_data_key, "")).strip()
        # fallback to credential bundle
        if not value and f.credential_key:
            value = str(getattr(credentials, f.credential_key, "") or "").strip()
        if value:
            pairs.append((f.label, value))

    return pairs


def format_platform_credentials(
    platform: str,
    credentials: CredentialBundle,
    raw_data: dict[str, Any] | None = None,
    *,
    separator: str = "\n",
    strip_url_scheme: bool = False,
    disclaimer: str = "",
) -> str:
    """Format credentials as a single string for marketplace delivery.

    Args:
        platform: GTA V platform name (e.g. "PlayStation 5", "PC - Legacy").
        credentials: The account's credential bundle.
        raw_data: Extra fields from OwnedProduct.raw_data or source envelope.
        separator: Line separator — ``"\\n"`` for most, ``"<br><br>"`` for PA.
        strip_url_scheme: Remove ``https?://`` prefix from link values.
        disclaimer: Appended at the end if non-empty.
    """
    pairs = resolve_platform_credentials(platform, credentials, raw_data)

    lines: list[str] = []
    for label, value in pairs:
        if strip_url_scheme and "link" in label.lower():
            value = re.sub(r"^https?://", "", value)
        lines.append(f"{label}: {value}")

    if disclaimer:
        lines.append(disclaimer)

    return separator.join(lines)
