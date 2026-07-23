"""Human-visible tracking references for PlayerAuctions listings.

New listings use the concise MCT-style ``#ABC123`` suffix.  The code is derived
from the posting attempt rather than credentials, so it is retry-stable and
safe to expose in a marketplace title.  Legacy bracketed PA codes remain
recognised only for order reconciliation during the transition.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

PA_TITLE_MAX_LENGTH = 150
_SHORT_CODE_RE = re.compile(r"(?<![A-Z0-9])#[A-Z0-9]{6,8}\b", re.IGNORECASE)
_LEGACY_TRACKING_CODE_RE = re.compile(
    r"\[PA-(?:J\d+-I\d+|P\d+-K\d+-A[0-9A-F]{8})\]",
    re.IGNORECASE,
)
PA_TRACKING_CODE_RE = re.compile(
    rf"(?:{_SHORT_CODE_RE.pattern}|{_LEGACY_TRACKING_CODE_RE.pattern})",
    re.IGNORECASE,
)
_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _short_code(seed: str) -> str:
    """Return a deterministic six-character MCT-style code for ``seed``."""
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
    chars: list[str] = []
    for _ in range(6):
        chars.append(_CODE_ALPHABET[value % len(_CODE_ALPHABET)])
        value //= len(_CODE_ALPHABET)
    return "#" + "".join(chars)


def tracking_code_for_item(item: Any) -> str:
    """Return a concise, durable code for one posting job item."""
    item_id = getattr(item, "id", None)
    job_id = getattr(item, "job_id", None)
    if not item_id or not job_id:
        raise ValueError("PlayerAuctions tracking code requires a saved posting job item")
    return _short_code(f"pa-job:{job_id}:item:{item_id}")


def append_tracking_code_for_code(
    title: str,
    code: str,
    *,
    max_length: int = PA_TITLE_MAX_LENGTH,
) -> str:
    """Replace any old generated suffix and append one concise code."""
    normalized_code = str(code or "").strip().upper()
    if not _SHORT_CODE_RE.fullmatch(normalized_code):
        raise ValueError("PlayerAuctions tracking code must use # plus six to eight letters or digits")
    suffix = f" {normalized_code}"
    if len(suffix) >= max_length:
        raise ValueError("PlayerAuctions title limit is too short for a tracking code")

    base = _LEGACY_TRACKING_CODE_RE.sub(" ", str(title or ""))
    base = _SHORT_CODE_RE.sub(" ", base)
    base = " ".join(base.split())
    base = base[: max_length - len(suffix)].rstrip()
    return f"{base}{suffix}" if base else normalized_code


def pool_clone_tracking_code(pool: Any, item: Any, attempt_token: Any) -> str:
    """Return a compact, retry-stable code for one PlayerAuctions pool clone."""
    pool_id = getattr(pool, "pk", None) or getattr(pool, "id", None)
    item_id = getattr(item, "pk", None) or getattr(item, "id", None)
    token = str(attempt_token or "").replace("-", "").upper()
    if not pool_id or not item_id or not token:
        raise ValueError("PlayerAuctions pool tracking code requires pool, item, and attempt token")
    return _short_code(f"pa-pool:{pool_id}:item:{item_id}:attempt:{token}")


def append_tracking_code(title: str, item: Any, *, max_length: int = PA_TITLE_MAX_LENGTH) -> str:
    """Append the posting item's concise PlayerAuctions code within the title limit."""
    return append_tracking_code_for_code(
        title,
        tracking_code_for_item(item),
        max_length=max_length,
    )


def extract_tracking_code(*values: Any) -> str:
    """Return the first short or legacy generated code found in text values."""
    for value in values:
        match = PA_TRACKING_CODE_RE.search(str(value or ""))
        if match:
            return match.group(0).strip().upper().strip("[]")
    return ""
