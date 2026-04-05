"""LZT item → OwnedProduct field mapping."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from apps.sync.services.shared.credentials import ParsedCredentials


def extract_remote_id(item: dict) -> str:
    return str(item.get('item_id') or '').strip()


def extract_login_data(item: dict) -> tuple[str, str]:
    """Return (login, password) from loginData.

    Raises ValueError if loginData is missing or incomplete.
    """
    login_data = item.get('loginData')
    if not login_data:
        raise ValueError(f"item {item.get('item_id')}: loginData missing")

    login = (login_data.get('login') or '').strip()
    password = (login_data.get('password') or '').strip()

    if not login or not password:
        raise ValueError(
            f"item {item.get('item_id')}: loginData incomplete "
            f"(login={bool(login)}, password={bool(password)})"
        )
    return login, password


def extract_email_data(item: dict) -> tuple[str, str]:
    """Return (email_login, email_password) from emailLoginData.

    Returns ('', '') if emailLoginData is missing.
    """
    email_data = item.get('emailLoginData')
    if not email_data:
        return '', ''

    return (
        (email_data.get('login') or '').strip(),
        (email_data.get('password') or '').strip(),
    )


def extract_category_id(item: dict) -> int:
    """Return LZT category_id from item."""
    cat_id = item.get('category_id') or (item.get('category') or {}).get('category_id')
    if not cat_id:
        raise ValueError(f"item {item.get('item_id')}: category_id missing")
    return int(cat_id)


def extract_price(item: dict) -> tuple[Decimal, str]:
    """Return (price, currency)."""
    price = item.get('price')
    currency = (item.get('price_currency') or 'usd').upper()
    if price is not None:
        return Decimal(str(price)), currency
    return Decimal('0'), currency


def extract_purchased_at(item: dict) -> datetime | None:
    """Return purchase datetime from buyer.operation_date."""
    buyer = item.get('buyer') or {}
    ts = buyer.get('operation_date')
    if ts:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return None


def make_password_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def to_parsed_credentials(item: dict) -> ParsedCredentials:
    """Convert LZT item data to ParsedCredentials for the shared helper."""
    login, password = extract_login_data(item)
    email, email_password = extract_email_data(item)
    return ParsedCredentials(
        login=login,
        password=password,
        email=email,
        email_password=email_password,
    )


def has_login_data(item: dict) -> bool:
    login_data = item.get('loginData')
    if not login_data:
        return False
    return bool(login_data.get('login')) and bool(login_data.get('password'))
