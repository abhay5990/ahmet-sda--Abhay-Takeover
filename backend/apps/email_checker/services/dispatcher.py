"""Domain -> check method router."""
from __future__ import annotations

from .domains import get_domain, is_gmail_domain, is_outlook_domain
from .types import CheckMethod


def classify(email: str) -> CheckMethod:
    """Decide which provider should verify the given email.

    Returns:
        ``CheckMethod.LZT``  for Microsoft-family domains.
        ``CheckMethod.SKIP`` for Gmail or malformed input.
        ``CheckMethod.IMAP`` for everything else (hardcoded mapping + fallback).
    """
    domain = get_domain(email)
    if not domain:
        return CheckMethod.SKIP
    if is_outlook_domain(domain):
        return CheckMethod.LZT
    if is_gmail_domain(domain):
        return CheckMethod.SKIP
    return CheckMethod.IMAP
