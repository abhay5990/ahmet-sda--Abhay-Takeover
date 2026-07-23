"""Stable, human-visible tracking references for PlayerAuctions listings.

A code is derived from the posting job item rather than account credentials.  It is
therefore unique for every listing attempt, remains stable across a retry of that
same attempt, and changes naturally whenever an account is relisted through a
new job item.
"""
from __future__ import annotations

import re
from typing import Any

PA_TITLE_MAX_LENGTH = 150
PA_TRACKING_CODE_RE = re.compile(
    r"\[PA-(?:J\d+-I\d+|P\d+-K\d+-A[0-9A-F]{8})\]",
    re.IGNORECASE,
)


def tracking_code_for_item(item: Any) -> str:
    """Return the durable PlayerAuctions code for one posting job item.

    ``PostingJobItem.id`` is globally unique and ``job_id`` makes the code easy
    for staff to trace back to the originating batch without exposing account
    credentials in a marketplace title.
    """
    item_id = getattr(item, "id", None)
    job_id = getattr(item, "job_id", None)
    if not item_id or not job_id:
        raise ValueError("PlayerAuctions tracking code requires a saved posting job item")
    return f"PA-J{job_id}-I{item_id}"


def append_tracking_code_for_code(
    title: str,
    code: str,
    *,
    max_length: int = PA_TITLE_MAX_LENGTH,
) -> str:
    """Append one validated PlayerAuctions code while retaining the title pattern.

    The function removes only an earlier generated code, so a selected target's
    visible wording stays unchanged when a new clone is created.
    """
    normalized_code = str(code or "").strip().upper()
    if not normalized_code.startswith("PA-"):
        raise ValueError("PlayerAuctions tracking code must start with PA-")
    suffix = f" [{normalized_code}]"
    if len(suffix) >= max_length:
        raise ValueError("PlayerAuctions title limit is too short for a tracking code")

    base = PA_TRACKING_CODE_RE.sub(" ", str(title or ""))
    base = " ".join(base.split())
    base = base[: max_length - len(suffix)].rstrip()
    return f"{base}{suffix}" if base else f"[{normalized_code}]"


def pool_clone_tracking_code(pool: Any, item: Any, attempt_token: Any) -> str:
    """Return a unique, retry-stable code for one PlayerAuctions pool clone.

    A pool item may be returned to stock and later relisted.  Its persisted
    attempt token makes that later listing distinct without exposing credentials
    in the marketplace title.
    """
    pool_id = getattr(pool, "pk", None) or getattr(pool, "id", None)
    item_id = getattr(item, "pk", None) or getattr(item, "id", None)
    token = str(attempt_token or "").replace("-", "").upper()[:8]
    if not pool_id or not item_id or len(token) != 8:
        raise ValueError("PlayerAuctions pool tracking code requires pool, item, and attempt token")
    return f"PA-P{pool_id}-K{item_id}-A{token}"


def append_tracking_code(title: str, item: Any, *, max_length: int = PA_TITLE_MAX_LENGTH) -> str:
    """Append the posting item's durable PlayerAuctions code within the title limit."""
    return append_tracking_code_for_code(
        title,
        tracking_code_for_item(item),
        max_length=max_length,
    )


def extract_tracking_code(*values: Any) -> str:
    """Return the first generated PlayerAuctions code found in text values."""
    for value in values:
        match = PA_TRACKING_CODE_RE.search(str(value or ""))
        if match:
            return match.group(0).strip("[]").upper()
    return ""
