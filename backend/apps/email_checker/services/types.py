"""Shared types for the email checker pipeline.

Framework-free dataclasses / enums used by every layer
(dispatcher, providers, report writer).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CheckMethod(str, Enum):
    """Which backend verified the credentials."""

    LZT = "lzt"
    IMAP = "imap"
    SKIP = "skip"


class CheckStatus(str, Enum):
    """Final outcome of a single ``email:password`` check."""

    VALID = "valid"
    INVALID = "invalid"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(slots=True)
class Letter:
    """Normalized inbox letter — same shape whether sourced from LZT or IMAP."""

    from_addr: str
    subject: str
    date: int                 # unix timestamp (0 if unparseable)
    text_plain: str = ""
    text_html: str = ""


@dataclass(slots=True)
class CheckResult:
    """Result row produced by a provider check."""

    email: str
    status: CheckStatus
    method: CheckMethod
    detail: str = ""
    letters: list[Letter] = field(default_factory=list)
    keyword_hits: dict[str, int] = field(default_factory=dict)
    sender_hits: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable projection (passwords are never included)."""
        return {
            "email": self.email,
            "status": self.status.value,
            "method": self.method.value,
            "detail": self.detail,
            "letter_count": len(self.letters),
            "letters": [
                {"from": l.from_addr, "subject": l.subject, "date": l.date}
                for l in self.letters
            ],
            "keyword_hits": self.keyword_hits,
            "sender_hits": self.sender_hits,
            "elapsed_ms": self.elapsed_ms,
        }
