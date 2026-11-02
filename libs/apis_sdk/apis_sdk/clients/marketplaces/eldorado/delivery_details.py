"""Eldorado account-delivery wire format (Oct 2026 contract).

Eldorado's ``POST /api/flexibleOffers/account`` no longer reads the legacy
``accountSecretDetails`` string array. Inventory is now an array of structured
``accountDeliveryDetails`` entries (one per account unit); the offer quantity
is derived from the entry count, so the legacy field produces
"Quantity of 0" / 400 errors. Proven live for MCT on 23 Oct 2026.

SDA keeps building ``accountSecretDetails`` strings internally (pools merge and
count them), and this module converts them at the wire boundary:

    {"accountDetails": {"accountLogin", "accountPassword"},
     "emailDetails": {"emailLogin", "emailPassword", "emailProviderUrl"} | None,
     "mfaDetails": None,
     "additionalInfo": str | None}

Absent optional parts are ``None`` (never "", never an object with null
fields, never []) — Eldorado rejects partial objects. Nothing is invented:
an entry without a recognisable login AND password raises
``EldoradoDeliveryDetailsError`` so the caller fails closed instead of
creating an offer the buyer cannot use.
"""

from __future__ import annotations

import re
from typing import Any

ADDITIONAL_INFO_MAX = 2000

_LOGIN_LABELS = (
    "login", "username", "user name", "account login", "account", "id",
    "psn id", "xbox id", "steam id", "steam login", "epic login", "riot id",
    "riot login", "ubisoft login", "rockstar id", "rockstar login",
)
_PASSWORD_LABELS = (
    "password", "pass", "account password", "psn password", "xbox password",
    "steam password", "epic password", "riot password", "ubisoft password",
    "rockstar password",
)
_EMAIL_LABELS = ("email", "e-mail", "mail", "email login")
_EMAIL_PASSWORD_LABELS = ("email password", "e-mail password", "mail password", "email pass")
_EMAIL_URL_LABELS = ("email login link", "provider url", "email provider url", "email link")

_SECTION_HEADERS = {
    "account details": "account",
    "email details": "email",
    "2fa details": "mfa",
    "additional information": "info",
}

_PROVIDER_URLS = {
    "gmail.com": "https://mail.google.com",
    "googlemail.com": "https://mail.google.com",
    "hotmail.com": "https://outlook.live.com",
    "outlook.com": "https://outlook.live.com",
    "live.com": "https://outlook.live.com",
    "msn.com": "https://outlook.live.com",
    "yahoo.com": "https://mail.yahoo.com",
    "yandex.com": "https://mail.yandex.com",
    "yandex.ru": "https://mail.yandex.com",
    "icloud.com": "https://www.icloud.com/mail",
    "me.com": "https://www.icloud.com/mail",
    "proton.me": "https://mail.proton.me",
    "protonmail.com": "https://mail.proton.me",
    "rambler.ru": "https://mail.rambler.ru",
    "mail.ru": "https://e.mail.ru",
}

_LINE = re.compile(r"^\s*([^:]{1,40}?)\s*:\s*(.*?)\s*$")


class EldoradoDeliveryDetailsError(ValueError):
    """A credential entry cannot be expressed as an Eldorado delivery detail."""


def _provider_url(email: str, explicit: str) -> str | None:
    explicit = (explicit or "").strip()
    if explicit:
        return explicit if re.match(r"^https?://", explicit, re.I) else f"https://{explicit}"
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return _PROVIDER_URLS.get(domain)


def secret_text_to_delivery_detail(text: str) -> dict[str, Any]:
    """Convert one legacy multiline secret entry into a structured detail."""
    raw = str(text or "").strip()
    if not raw:
        raise EldoradoDeliveryDetailsError("empty credential entry")

    section = None
    login = password = email = email_password = email_url = ""
    leftovers: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        header = _SECTION_HEADERS.get(stripped.lower().rstrip(":"))
        if header:
            section = header
            continue
        m = _LINE.match(stripped)
        label = m.group(1).strip().lower() if m else ""
        value = m.group(2).strip() if m else ""

        if section == "email" and m:
            if label in ("login", *_EMAIL_LABELS) and not email:
                email = value
                continue
            if label in ("password", *_EMAIL_PASSWORD_LABELS) and not email_password:
                email_password = value
                continue
            if label in _EMAIL_URL_LABELS and not email_url:
                email_url = value
                continue
        elif section in (None, "account") and m and value:
            if label in _EMAIL_PASSWORD_LABELS and not email_password:
                email_password = value
                continue
            if label in _EMAIL_URL_LABELS and not email_url:
                email_url = value
                continue
            if label in _EMAIL_LABELS and not email:
                email = value
                continue
            if label in _LOGIN_LABELS and not login:
                login = value
                continue
            if label in _PASSWORD_LABELS and not password:
                password = value
                continue
        leftovers.append(stripped)

    if not login or not password:
        raise EldoradoDeliveryDetailsError(
            "credential entry has no recognisable account login and password"
        )

    url = _provider_url(email, email_url) if email else None
    email_details = None
    if email and email_password and url:
        email_details = {"emailLogin": email, "emailPassword": email_password, "emailProviderUrl": url}
    elif email or email_password:
        # Never drop email access the buyer paid for: keep it as delivery text.
        if email:
            leftovers.insert(0, f"Email: {email}")
        if email_password:
            leftovers.insert(1 if email else 0, f"Email Password: {email_password}")
        if email_url:
            leftovers.append(f"Email Login Link: {email_url}")

    info = "\n".join(leftovers).strip()[:ADDITIONAL_INFO_MAX] or None
    return {
        "accountDetails": {"accountLogin": login, "accountPassword": password},
        "emailDetails": email_details,
        "mfaDetails": None,
        "additionalInfo": info,
    }


def to_wire_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy where legacy ``accountSecretDetails`` became ``accountDeliveryDetails``.

    - Payloads that already carry ``accountDeliveryDetails`` are left alone.
    - An empty/absent secret list (e.g. dropship, which never sends secrets)
      simply drops the legacy key.
    """
    if not isinstance(payload, dict):
        return payload
    wire = dict(payload)
    # Eldorado's own form sends volumeDiscounts as null, never [].
    details = wire.get("details")
    if isinstance(details, dict) and isinstance(details.get("pricing"), dict) \
            and details["pricing"].get("volumeDiscounts") == []:
        wire["details"] = {**details, "pricing": {**details["pricing"], "volumeDiscounts": None}}
    if "accountSecretDetails" not in wire:
        return wire
    secrets = wire.pop("accountSecretDetails")
    if "accountDeliveryDetails" in wire:
        return wire
    if isinstance(secrets, str):
        secrets = [secrets]
    entries = [s for s in (secrets or []) if str(s or "").strip()]
    if entries:
        wire["accountDeliveryDetails"] = [secret_text_to_delivery_detail(s) for s in entries]
    return wire
