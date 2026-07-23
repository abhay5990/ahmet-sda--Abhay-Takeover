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
PA_TRACKING_CODE_RE = re.compile(r"\[PA-J\d+-I\d+\]", re.IGNORECASE)


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


def append_tracking_code(title: str, item: Any, *, max_length: int = PA_TITLE_MAX_LENGTH) -> str:
    """Append the item's PlayerAuctions tracking code within the title limit.

    Any previous generated code is replaced.  This prevents a relisted account
    from carrying an old reference while keeping ordinary title text intact.
    """
    code = tracking_code_for_item(item)
    suffix = f" [{code}]"
    if len(suffix) >= max_length:
        raise ValueError("PlayerAuctions title limit is too short for a tracking code")

    base = PA_TRACKING_CODE_RE.sub(" ", str(title or ""))
    base = " ".join(base.split())
    base = base[: max_length - len(suffix)].rstrip()
    return f"{base}{suffix}" if base else f"[{code}]"


def extract_tracking_code(*values: Any) -> str:
    """Return the first generated PlayerAuctions code found in text values."""
    for value in values:
        match = PA_TRACKING_CODE_RE.search(str(value or ""))
        if match:
            return match.group(0).strip("[]").upper()
    return ""
