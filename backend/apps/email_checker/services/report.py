"""JSON + CSV output writers.

Passwords are NEVER written: ``CheckResult.to_dict`` does not expose
the password field (there is no password field on ``CheckResult``).
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .types import CheckResult


def write_json(results: list[CheckResult], path: Path) -> None:
    """Write a JSON report with ISO-8601 ``generated_at`` metadata."""
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_csv(results: list[CheckResult], path: Path) -> None:
    """Write a flat CSV report (JSON-encoded columns for hit maps)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "email", "status", "method", "detail",
            "letter_count", "keyword_hits", "sender_hits", "elapsed_ms",
        ])
        for r in results:
            writer.writerow([
                r.email,
                r.status.value,
                r.method.value,
                r.detail,
                len(r.letters),
                json.dumps(r.keyword_hits, ensure_ascii=False),
                json.dumps(r.sender_hits, ensure_ascii=False),
                r.elapsed_ms,
            ])
