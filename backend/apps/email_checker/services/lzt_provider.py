"""LZT ``/letters2`` based email checker.

Wraps an ``LztFacade`` instance; the facade already handles auth, proxy
rotation, retry (including body-level ``retry_request``), and rate-limiting.
This layer only maps the SDK result into a ``CheckResult``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .input_parser import mask_email
from .types import CheckMethod, CheckResult, CheckStatus, Letter

logger = logging.getLogger(__name__)


class LztEmailChecker:
    """Business-layer adapter that delegates to ``LztFacade.get_email_letters``."""

    def __init__(self, facade: Any, proxy_group: str | None) -> None:
        """
        Args:
            facade: ``LztFacade`` instance (typed as Any to keep this module
                framework-free and avoid a hard SDK import in Django settings-time).
            proxy_group: Proxy group name passed to the facade on every call.
        """
        self._facade = facade
        self._proxy_group = proxy_group

    def check(
        self,
        email: str,
        password: str,
        *,
        fetch_limit: int = 50,
        keywords: list[str] | None = None,
        senders: list[str] | None = None,
    ) -> CheckResult:
        """Validate one ``email:password`` pair and optionally scan the inbox."""
        started = time.monotonic()
        credential = f"{email}:{password}"
        limit = max(10, fetch_limit) if fetch_limit else 10

        # Facade's execute_with_retry handles rate-limit retries automatically
        # (SDK client remaps LZT "must wait N seconds" → RATE_LIMIT category).
        result = self._facade.get_email_letters(
            credential, limit=limit, proxy_group=self._proxy_group,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        logger.debug(
            "LZT check %s -> ok=%s elapsed=%sms",
            mask_email(email), result.ok, elapsed_ms,
        )

        if result.ok and result.data is not None:
            letters = _parse_letters(result.data.get("letters") or [])
            return CheckResult(
                email=email,
                status=CheckStatus.VALID,
                method=CheckMethod.LZT,
                detail="ok",
                letters=letters,
                keyword_hits=_count_keywords(letters, keywords or []),
                sender_hits=_count_senders(letters, senders or []),
                elapsed_ms=elapsed_ms,
            )

        err = result.error
        code = err.category.value if err else "unknown"
        message = (err.message if err else "") or ""
        msg_lower = message.lower()

        # Classify based on error category + message content.
        # (status_code is unreliable — facade may not propagate it.)
        if code == "authentication" and any(
            kw in msg_lower for kw in (
                "invalid", "wrong password", "incorrect",
                "not valid", "locked", "disabled",
            )
        ):
            check_status = CheckStatus.INVALID
            detail = f"invalid_credentials: {message}"
        elif code == "authentication" and "wait" not in msg_lower:
            check_status = CheckStatus.ERROR
            detail = f"auth_error: {message}" if message else "auth_error"
        else:
            check_status = CheckStatus.ERROR
            detail = f"{code}: {message}" if message else code

        return CheckResult(
            email=email,
            status=check_status,
            method=CheckMethod.LZT,
            detail=detail,
            elapsed_ms=elapsed_ms,
        )


def _parse_letters(raw: list[dict[str, Any]]) -> list[Letter]:
    out: list[Letter] = []
    for item in raw:
        text_plain = str(item.get("textPlain") or "")
        subject_raw = item.get("subject")
        subject = str(subject_raw) if subject_raw else (
            text_plain.splitlines()[0][:200] if text_plain else ""
        )
        try:
            date_val = int(item.get("date") or 0)
        except (TypeError, ValueError):
            date_val = 0
        out.append(Letter(
            from_addr=str(item.get("from") or ""),
            subject=subject,
            date=date_val,
            text_plain=text_plain,
            text_html=str(item.get("textHtml") or ""),
        ))
    return out


def _count_keywords(letters: list[Letter], keywords: list[str]) -> dict[str, int]:
    # LZT responses have no real subject header — Letter.subject here is a
    # preview derived from the first line of text_plain, so scanning both
    # would double-count.  Scan only text_plain.
    hits: dict[str, int] = {}
    for kw in keywords:
        kw_low = kw.lower().strip()
        if not kw_low:
            continue
        hits[kw] = sum(l.text_plain.lower().count(kw_low) for l in letters)
    return hits


def _count_senders(letters: list[Letter], senders: list[str]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for s in senders:
        s_low = s.lower().strip()
        if not s_low:
            continue
        hits[s] = sum(1 for l in letters if s_low in l.from_addr.lower())
    return hits
