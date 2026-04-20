"""Tests for ImapEmailChecker — imaplib + socket are monkey-patched."""
from __future__ import annotations

import imaplib
import socket
from typing import Any

import pytest

from apps.email_checker.services import imap_provider
from apps.email_checker.services.imap_provider import ImapEmailChecker
from apps.email_checker.services.types import CheckMethod, CheckStatus


# ---------------------------------------------------------------------------
# Fake IMAP server
# ---------------------------------------------------------------------------


class _FakeImap:
    """Minimal imaplib.IMAP4_SSL substitute."""

    def __init__(self, *, login_ok: bool = True, error_msg: str | None = None,
                 letters: list[dict[str, bytes]] | None = None) -> None:
        self._login_ok = login_ok
        self._error_msg = error_msg
        self._letters = letters or []
        self.logged_out = False
        self.logged_in = False

    def login(self, user: str, password: str):
        if not self._login_ok:
            raise imaplib.IMAP4.error(self._error_msg or "AUTHENTICATIONFAILED invalid")
        self.logged_in = True
        return ("OK", [b"logged in"])

    def select(self, mailbox: str, readonly: bool = False):
        return ("OK", [b"1"])

    def search(self, charset, criterion):
        if not self._letters:
            return ("OK", [b""])
        ids = b" ".join(str(i + 1).encode() for i in range(len(self._letters)))
        return ("OK", [ids])

    def fetch(self, mid: bytes, parts: str):
        try:
            idx = int(mid.decode()) - 1
            item = self._letters[idx]
        except (ValueError, IndexError):
            return ("NO", [None])
        raw = item.get("raw", b"")
        return ("OK", [(b"1 (RFC822 {%d}" % len(raw), raw)])

    def logout(self):
        self.logged_out = True


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImap | Exception) -> None:
    """Install a factory that returns the given fake (or raises)."""
    def _factory(host, port, timeout=None):
        if isinstance(fake, Exception):
            raise fake
        return fake
    monkeypatch.setattr(imap_provider.imaplib, "IMAP4_SSL", _factory)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestValidLogin:
    def test_login_ok_no_fetch(self, monkeypatch: pytest.MonkeyPatch):
        fake = _FakeImap(login_ok=True)
        _install(monkeypatch, fake)

        result = ImapEmailChecker().check("user@yahoo.com", "pw", fetch_limit=0)

        assert result.status == CheckStatus.VALID
        assert result.method == CheckMethod.IMAP
        assert result.detail == "ok"
        assert fake.logged_in
        assert fake.logged_out

    def test_fetch_limit_returns_letters(self, monkeypatch: pytest.MonkeyPatch):
        raw = (
            b"From: noreply@yahoo.com\r\n"
            b"Subject: Hello\r\n"
            b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
            b"\r\n"
            b"Hello body"
        )
        fake = _FakeImap(login_ok=True, letters=[{"raw": raw}])
        _install(monkeypatch, fake)

        result = ImapEmailChecker().check("u@yahoo.com", "pw", fetch_limit=5)

        assert result.status == CheckStatus.VALID
        assert len(result.letters) == 1
        assert result.letters[0].subject == "Hello"
        assert "noreply@yahoo.com" in result.letters[0].from_addr

    def test_keyword_scan(self, monkeypatch: pytest.MonkeyPatch):
        raw = (
            b"From: n@y.com\r\n"
            b"Subject: token token\r\n"
            b"\r\n"
            b"Body with TOKEN inside"
        )
        fake = _FakeImap(login_ok=True, letters=[{"raw": raw}])
        _install(monkeypatch, fake)

        result = ImapEmailChecker().check(
            "u@yahoo.com", "pw", fetch_limit=5, keywords=["token"],
        )

        # 2 in subject + 1 in body
        assert result.keyword_hits["token"] == 3


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestInvalidLogin:
    def test_wrong_password_invalid(self, monkeypatch: pytest.MonkeyPatch):
        fake = _FakeImap(login_ok=False, error_msg="AUTHENTICATIONFAILED invalid credentials")
        _install(monkeypatch, fake)

        result = ImapEmailChecker().check("u@yahoo.com", "bad", fetch_limit=0)

        assert result.status == CheckStatus.INVALID
        assert "invalid_credentials" in result.detail
        assert fake.logged_out


class TestConnectionErrors:
    def test_host_unreachable(self, monkeypatch: pytest.MonkeyPatch):
        _install(monkeypatch, socket.gaierror("Name or service not known"))

        result = ImapEmailChecker().check("u@broken.xyz", "pw", fetch_limit=0)

        assert result.status == CheckStatus.ERROR
        assert "host_unreachable" in result.detail

    def test_generic_connect_error(self, monkeypatch: pytest.MonkeyPatch):
        _install(monkeypatch, RuntimeError("unexpected"))

        result = ImapEmailChecker().check("u@yahoo.com", "pw", fetch_limit=0)

        assert result.status == CheckStatus.ERROR
        assert "connect_error" in result.detail

    def test_malformed_email(self):
        result = ImapEmailChecker().check("no-at-sign", "pw", fetch_limit=0)
        assert result.status == CheckStatus.ERROR
        assert "malformed_email" in result.detail


# ---------------------------------------------------------------------------
# Server mapping
# ---------------------------------------------------------------------------


class TestServerMapping:
    def test_yahoo_uses_hardcoded_host(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}

        def _factory(host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port
            return _FakeImap(login_ok=True)

        monkeypatch.setattr(imap_provider.imaplib, "IMAP4_SSL", _factory)

        ImapEmailChecker().check("u@yahoo.com", "pw", fetch_limit=0)

        assert captured["host"] == "imap.mail.yahoo.com"
        assert captured["port"] == 993

    def test_unknown_domain_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}

        def _factory(host, port, timeout=None):
            captured["host"] = host
            return _FakeImap(login_ok=True)

        monkeypatch.setattr(imap_provider.imaplib, "IMAP4_SSL", _factory)

        ImapEmailChecker().check("u@custom.tld", "pw", fetch_limit=0)

        assert captured["host"] == "imap.custom.tld"
