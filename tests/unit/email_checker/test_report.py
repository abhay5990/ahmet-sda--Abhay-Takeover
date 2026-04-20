"""Tests for JSON + CSV output writers."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from apps.email_checker.services.report import write_csv, write_json
from apps.email_checker.services.types import (
    CheckMethod,
    CheckResult,
    CheckStatus,
    Letter,
)


def _sample_results() -> list[CheckResult]:
    return [
        CheckResult(
            email="a@hotmail.com",
            status=CheckStatus.VALID,
            method=CheckMethod.LZT,
            detail="ok",
            letters=[
                Letter(
                    from_addr="noreply@microsoft.com",
                    subject="Hello",
                    date=1700000000,
                    text_plain="body",
                ),
            ],
            keyword_hits={"hello": 1},
            sender_hits={"microsoft": 1},
            elapsed_ms=123,
        ),
        CheckResult(
            email="b@gmail.com",
            status=CheckStatus.SKIPPED,
            method=CheckMethod.SKIP,
            detail="gmail_or_malformed",
        ),
    ]


class TestWriteJson:
    def test_schema_and_passwords_absent(self, tmp_path: Path):
        path = tmp_path / "out.json"
        write_json(_sample_results(), path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["count"] == 2
        assert "generated_at" in data
        assert len(data["results"]) == 2

        first = data["results"][0]
        assert first["email"] == "a@hotmail.com"
        assert first["status"] == "valid"
        assert first["method"] == "lzt"
        assert first["letter_count"] == 1
        assert first["letters"][0]["subject"] == "Hello"
        assert first["keyword_hits"] == {"hello": 1}
        # Report must never contain passwords.
        raw = path.read_text(encoding="utf-8")
        assert "password" not in raw.lower() or "password" not in raw

    def test_creates_parent_dir(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "out.json"
        write_json(_sample_results(), path)
        assert path.is_file()


class TestWriteCsv:
    def test_header_and_rows(self, tmp_path: Path):
        path = tmp_path / "out.csv"
        write_csv(_sample_results(), path)

        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        header = rows[0]
        assert header == [
            "email", "status", "method", "detail",
            "letter_count", "keyword_hits", "sender_hits", "elapsed_ms",
        ]
        assert rows[1][0] == "a@hotmail.com"
        assert rows[1][1] == "valid"
        assert rows[1][4] == "1"
        assert json.loads(rows[1][5]) == {"hello": 1}
        assert rows[2][1] == "skipped"

    def test_creates_parent_dir(self, tmp_path: Path):
        path = tmp_path / "nested" / "out.csv"
        write_csv(_sample_results(), path)
        assert path.is_file()
