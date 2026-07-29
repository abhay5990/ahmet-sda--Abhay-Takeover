"""Content-aware parsing of tab-separated account credential rows.

This mirrors the frontend smart paste parser in
``frontend/templates/posting/restock_pool_detail.html`` (``_detectColumnsForDetail``
with no spec): the first two cells are login/password, and every remaining cell
is classified by content into canonical fields. Keeping the logic here lets
server-side tooling (e.g. the backfill management command) parse the same paste
format the UI accepts, without duplicating the rules.
"""
from __future__ import annotations

import re

# A date like 1/2/2003 or 2003-02-01 → birthday.
_DATE_RE = re.compile(r"^\d{1,4}[/.\\-]\d{1,2}[/.\\-]\d{1,4}$")
# A domain / email-login-link like "outlook.com" or "mx.duolashop.com/outlook.com".
# A '/' inside one cell is kept whole (two domains for one account), never split.
_LINK_RE = re.compile(r"^(https?://)?[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)

# Canonical field keys the parser can produce, in a stable order.
CANONICAL_FIELDS = (
    "login",
    "password",
    "email",
    "email_password",
    "email_login_link",
    "security_email",
    "security_email_password",
    "birthday",
)

# Header tokens that indicate the first line is a header row, not data.
_HEADER_TOKENS = frozenset({
    "login", "password", "email", "email password", "email_password",
    "email domain", "recovery email", "recovery email pass",
    "psn id", "xbox id", "steam id", "loginname",
})


def parse_credential_row(cells: list[str]) -> dict[str, str]:
    """Parse one row of cells into canonical credential fields.

    - cells[0] -> login, cells[1] -> password
    - remaining cells: '@' value -> email then recovery(security) email;
      domain-like -> email_login_link (email domain, kept whole);
      date-like -> birthday; otherwise -> email_password then recovery pass.
    """
    cred = {key: "" for key in CANONICAL_FIELDS}
    if len(cells) >= 1:
        cred["login"] = cells[0].strip()
    if len(cells) >= 2:
        cred["password"] = cells[1].strip()

    email_seen = email_pass_seen = recovery_email_seen = False
    recovery_pass_seen = link_seen = False
    for raw in cells[2:]:
        val = raw.strip()
        if not val:
            continue
        if _DATE_RE.match(val):
            cred["birthday"] = val
        elif "@" in val:
            if not email_seen:
                cred["email"] = val
                email_seen = True
            elif not recovery_email_seen:
                cred["security_email"] = val
                recovery_email_seen = True
        elif _LINK_RE.match(val):
            if not link_seen:
                cred["email_login_link"] = val
                link_seen = True
        else:
            if not email_pass_seen:
                cred["email_password"] = val
                email_pass_seen = True
            elif not recovery_pass_seen:
                cred["security_email_password"] = val
                recovery_pass_seen = True
    return cred


def looks_like_header(cells: list[str]) -> bool:
    """True when a row appears to be a header (column labels), not credentials."""
    lowered = [c.strip().lower() for c in cells]
    return any(tok in _HEADER_TOKENS for tok in lowered)


def parse_credential_text(
    text: str,
    *,
    delimiter: str = "\t",
) -> list[dict[str, str]]:
    """Parse a multi-line paste/file into a list of canonical credential dicts.

    Skips blank lines and a leading header row when detected.
    """
    rows: list[dict[str, str]] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return rows
    if looks_like_header(lines[0].split(delimiter)):
        lines = lines[1:]
    for line in lines:
        cells = line.split(delimiter)
        rows.append(parse_credential_row(cells))
    return rows
