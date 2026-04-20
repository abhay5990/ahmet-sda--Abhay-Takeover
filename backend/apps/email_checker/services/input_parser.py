"""Parse ``email:password`` inputs from .txt or .csv files.

Both formats produce the same list of ``(email, password)`` tuples.
Password values are returned as-is (no trimming) so colons inside the
password are preserved via single-split on the first ':' separator.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

EmailPasswordPair = tuple[str, str]


def parse_file(path: Path) -> list[EmailPasswordPair]:
    """Parse a .txt or .csv file into ``(email, password)`` pairs."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig", errors="replace")  # BOM-tolerant
    if suffix == ".csv":
        return _parse_csv(text)
    return _parse_txt(text)


def _parse_txt(text: str) -> list[EmailPasswordPair]:
    pairs: list[EmailPasswordPair] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue  # malformed
        email, password = line.split(":", 1)  # password may contain ':'
        email = email.strip()
        if email:
            pairs.append((email, password))
    return pairs


def _parse_csv(text: str) -> list[EmailPasswordPair]:
    pairs: list[EmailPasswordPair] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row:
            continue
        cell0 = (row[0] or "").strip()
        if not cell0 or cell0.startswith("#"):
            continue
        # Header row tolerance: "email,password" or "e-mail,password"
        if cell0.lower() in {"email", "e-mail", "login"}:
            continue
        # Support both "email,password" (multi-col) and "email:password" (single-col)
        if len(row) >= 2:
            email, password = cell0, (row[1] or "")
        elif ":" in cell0:
            email, password = cell0.split(":", 1)
            email = email.strip()
        else:
            continue
        if email:
            pairs.append((email, password))
    return pairs


def mask_password(password: str) -> str:
    """Replace interior characters with ``*`` so logs never expose secrets."""
    if not password:
        return ""
    if len(password) <= 2:
        return "*" * len(password)
    return password[0] + "*" * (len(password) - 2) + password[-1]


def mask_email(email: str) -> str:
    """Expose the first three local chars + domain (or first char if short)."""
    if not email:
        return ""
    if "@" not in email:
        return email[:3] + "***"
    local, domain = email.split("@", 1)
    if len(local) <= 3:
        return local[:1] + "***@" + domain
    return local[:3] + "***@" + domain
