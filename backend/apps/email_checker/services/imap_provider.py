"""IMAPS login + inbox fetch + keyword/sender scan.

Basic-auth only.  Providers that require OAuth (Gmail, Outlook) should
be routed elsewhere by ``dispatcher.classify`` — anything that reaches
this module is expected to accept password authentication.
"""
from __future__ import annotations

import email as email_parser
import imaplib
import logging
import socket
import time
from email.utils import parsedate_to_datetime
from typing import Any

from .domains import get_domain, get_imap_server
from .input_parser import mask_email
from .types import CheckMethod, CheckResult, CheckStatus, Letter

logger = logging.getLogger(__name__)


class ImapEmailChecker:
    """Verifies credentials via IMAPS; optionally fetches last N letters."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def check(
        self,
        email_addr: str,
        password: str,
        *,
        fetch_limit: int = 0,
        keywords: list[str] | None = None,
        senders: list[str] | None = None,
    ) -> CheckResult:
        started = time.monotonic()
        domain = get_domain(email_addr)
        if not domain:
            return self._fail(email_addr, started, "malformed_email",
                              status=CheckStatus.ERROR)

        host, port = get_imap_server(domain)

        try:
            conn = imaplib.IMAP4_SSL(host, port, timeout=self._timeout)
        except (socket.gaierror, OSError) as exc:
            return self._fail(email_addr, started, "host_unreachable", detail=str(exc))
        except Exception as exc:
            return self._fail(email_addr, started, "connect_error", detail=str(exc))

        try:
            conn.login(email_addr, password)
        except imaplib.IMAP4.error as exc:
            _safe_logout(conn)
            msg = str(exc).lower()
            if any(k in msg for k in ("auth", "invalid", "login", "password")):
                return self._fail(email_addr, started, "invalid_credentials",
                                  status=CheckStatus.INVALID, detail=str(exc))
            return self._fail(email_addr, started, "imap_error", detail=str(exc))
        except Exception as exc:
            _safe_logout(conn)
            return self._fail(email_addr, started, "connect_error", detail=str(exc))

        letters: list[Letter] = []
        try:
            conn.select("INBOX", readonly=True)
            if fetch_limit > 0:
                typ, data = conn.search(None, "ALL")
                if typ == "OK" and data and data[0]:
                    ids = data[0].split()
                    latest_ids = ids[-fetch_limit:]
                    for mid in latest_ids:
                        letter = _fetch_letter(conn, mid)
                        if letter:
                            letters.append(letter)
        except Exception as exc:
            logger.warning(
                "IMAP fetch failed for %s: %s", mask_email(email_addr), exc,
            )
        finally:
            _safe_logout(conn)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return CheckResult(
            email=email_addr,
            status=CheckStatus.VALID,
            method=CheckMethod.IMAP,
            detail="ok",
            letters=letters,
            keyword_hits=_count_keywords(letters, keywords or []),
            sender_hits=_count_senders(letters, senders or []),
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def _fail(
        email_addr: str,
        started: float,
        code: str,
        *,
        status: CheckStatus = CheckStatus.ERROR,
        detail: str = "",
    ) -> CheckResult:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return CheckResult(
            email=email_addr,
            status=status,
            method=CheckMethod.IMAP,
            detail=f"{code}: {detail}" if detail else code,
            elapsed_ms=elapsed_ms,
        )


def _safe_logout(conn: Any) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001 — logout is best-effort
        pass


def _fetch_letter(conn: Any, mid: bytes) -> Letter | None:
    try:
        typ, data = conn.fetch(mid, "(RFC822)")
        if typ != "OK" or not data or not data[0]:
            return None
        raw = data[0][1]
        msg = email_parser.message_from_bytes(raw)
        body = _extract_body(msg)
        date_val = 0
        date_header = msg.get("Date")
        if date_header:
            try:
                date_val = int(parsedate_to_datetime(date_header).timestamp())
            except Exception:
                date_val = 0
        return Letter(
            from_addr=str(msg.get("From") or ""),
            subject=str(msg.get("Subject") or "")[:200],
            date=date_val,
            text_plain=body,
        )
    except Exception as exc:
        logger.debug("Fetch letter failed: %s", exc)
        return None


def _extract_body(msg: Any) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    except Exception:
        pass
    return ""


def _count_keywords(letters: list[Letter], keywords: list[str]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for kw in keywords:
        kw_low = kw.lower().strip()
        if not kw_low:
            continue
        hits[kw] = sum(
            (l.subject + " " + l.text_plain).lower().count(kw_low)
            for l in letters
        )
    return hits


def _count_senders(letters: list[Letter], senders: list[str]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for s in senders:
        s_low = s.lower().strip()
        if not s_low:
            continue
        hits[s] = sum(1 for l in letters if s_low in l.from_addr.lower())
    return hits
