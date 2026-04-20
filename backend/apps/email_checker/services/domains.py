"""Domain classification + IMAP server mapping.

Outlook-family domains (hotmail/outlook/live/msn) are validated via the
LZT Mail Access API because Microsoft disabled basic-auth IMAP in 2022.
Gmail is skipped outright (Google disabled basic-auth IMAP in 2022 too,
and their OAuth-only flow is out of scope for the Phase 1 PoC).
Everything else is verified via plain IMAPS.
"""
from __future__ import annotations

# LZT /letters2 handles these.  Prefix match (covers hotmail.com, hotmail.fr, ...).
OUTLOOK_DOMAINS: tuple[str, ...] = (
    "hotmail.",
    "outlook.",
    "live.",
    "msn.",
)

# Always skipped (basic-auth IMAP disabled by Google).
GMAIL_DOMAINS: tuple[str, ...] = (
    "gmail.",
    "googlemail.",
)

# Hardcoded IMAP server mapping (domain -> (host, port)).
# Unknown domains fall back to ``imap.<domain>:993``.
IMAP_SERVERS: dict[str, tuple[str, int]] = {
    "yahoo.com": ("imap.mail.yahoo.com", 993),
    "yahoo.co.uk": ("imap.mail.yahoo.com", 993),
    "yahoo.de": ("imap.mail.yahoo.com", 993),
    "yahoo.fr": ("imap.mail.yahoo.com", 993),
    "ymail.com": ("imap.mail.yahoo.com", 993),
    "rocketmail.com": ("imap.mail.yahoo.com", 993),
    "mail.ru": ("imap.mail.ru", 993),
    "inbox.ru": ("imap.mail.ru", 993),
    "list.ru": ("imap.mail.ru", 993),
    "bk.ru": ("imap.mail.ru", 993),
    "yandex.com": ("imap.yandex.com", 993),
    "yandex.ru": ("imap.yandex.ru", 993),
    "ya.ru": ("imap.yandex.ru", 993),
    "icloud.com": ("imap.mail.me.com", 993),
    "me.com": ("imap.mail.me.com", 993),
    "aol.com": ("imap.aol.com", 993),
    "gmx.com": ("imap.gmx.com", 993),
    "gmx.net": ("imap.gmx.net", 993),
    "web.de": ("imap.web.de", 993),
    "zoho.com": ("imap.zoho.com", 993),
}


def normalize_email(raw: str) -> str:
    """Lowercase + trim. Returns empty string if input is None/blank."""
    return (raw or "").strip().lower()


def get_domain(email: str) -> str:
    """Return the lower-cased domain after ``@``; empty if malformed."""
    normalized = normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[1]


def is_outlook_domain(domain: str) -> bool:
    return any(domain.startswith(prefix) for prefix in OUTLOOK_DOMAINS)


def is_gmail_domain(domain: str) -> bool:
    return any(domain.startswith(prefix) for prefix in GMAIL_DOMAINS)


def get_imap_server(domain: str) -> tuple[str, int]:
    """Return ``(host, port)`` for the IMAP connection.

    Falls back to ``imap.<domain>:993`` when the domain is not in the
    hardcoded mapping.  Callers should treat connection errors on the
    fallback as a "host_unreachable" failure.
    """
    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]
    return (f"imap.{domain}", 993)
