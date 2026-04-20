"""Tests for input file parser + masking helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.email_checker.services.input_parser import (
    mask_email,
    mask_password,
    parse_file,
)


# ---------------------------------------------------------------------------
# TXT format
# ---------------------------------------------------------------------------


class TestParseTxt:
    def test_basic_lines(self, tmp_path: Path):
        p = tmp_path / "in.txt"
        p.write_text("a@hotmail.com:pw1\nb@yahoo.com:pw2\n", encoding="utf-8")
        assert parse_file(p) == [
            ("a@hotmail.com", "pw1"),
            ("b@yahoo.com", "pw2"),
        ]

    def test_blank_and_comment_lines_skipped(self, tmp_path: Path):
        p = tmp_path / "in.txt"
        p.write_text(
            "# comment line\n"
            "\n"
            "a@hotmail.com:pw1\n"
            "   \n"
            "# another\n"
            "b@yahoo.com:pw2\n",
            encoding="utf-8",
        )
        assert parse_file(p) == [
            ("a@hotmail.com", "pw1"),
            ("b@yahoo.com", "pw2"),
        ]

    def test_password_with_colon_preserved(self, tmp_path: Path):
        p = tmp_path / "in.txt"
        p.write_text("a@hotmail.com:pw:with:colons\n", encoding="utf-8")
        assert parse_file(p) == [("a@hotmail.com", "pw:with:colons")]

    def test_malformed_lines_ignored(self, tmp_path: Path):
        p = tmp_path / "in.txt"
        p.write_text(
            "no-colon-here\n"
            "a@hotmail.com:pw1\n"
            ":no-email\n",
            encoding="utf-8",
        )
        assert parse_file(p) == [("a@hotmail.com", "pw1")]

    def test_utf8_bom_tolerance(self, tmp_path: Path):
        p = tmp_path / "in.txt"
        p.write_bytes(b"\xef\xbb\xbfa@hotmail.com:pw1\n")
        assert parse_file(p) == [("a@hotmail.com", "pw1")]


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------


class TestParseCsv:
    def test_two_column_csv(self, tmp_path: Path):
        p = tmp_path / "in.csv"
        p.write_text("a@hotmail.com,pw1\nb@yahoo.com,pw2\n", encoding="utf-8")
        assert parse_file(p) == [
            ("a@hotmail.com", "pw1"),
            ("b@yahoo.com", "pw2"),
        ]

    def test_header_row_skipped(self, tmp_path: Path):
        p = tmp_path / "in.csv"
        p.write_text(
            "email,password\n"
            "a@hotmail.com,pw1\n",
            encoding="utf-8",
        )
        assert parse_file(p) == [("a@hotmail.com", "pw1")]

    def test_single_column_with_colon(self, tmp_path: Path):
        p = tmp_path / "in.csv"
        p.write_text("a@hotmail.com:pw1\n", encoding="utf-8")
        assert parse_file(p) == [("a@hotmail.com", "pw1")]

    def test_comment_rows_skipped(self, tmp_path: Path):
        p = tmp_path / "in.csv"
        p.write_text(
            "# this is a note\n"
            "a@hotmail.com,pw1\n",
            encoding="utf-8",
        )
        assert parse_file(p) == [("a@hotmail.com", "pw1")]


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


class TestMasking:
    @pytest.mark.parametrize("pw,expected", [
        ("", ""),
        ("a", "*"),
        ("ab", "**"),
        ("abc", "a*c"),
        ("password", "p******d"),
    ])
    def test_mask_password(self, pw, expected):
        assert mask_password(pw) == expected

    def test_mask_email_normal(self):
        assert mask_email("alice@hotmail.com") == "ali***@hotmail.com"

    def test_mask_email_short_local(self):
        assert mask_email("ab@hotmail.com") == "a***@hotmail.com"

    def test_mask_email_no_at(self):
        assert mask_email("weird") == "wei***"

    def test_mask_email_empty(self):
        assert mask_email("") == ""
