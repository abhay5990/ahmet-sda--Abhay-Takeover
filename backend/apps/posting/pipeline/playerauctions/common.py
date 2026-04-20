"""PA common helpers — Excel column template, XLSX generation, shared field builders.

This module owns all PA-level knowledge that is not game-specific:
- TEMPLATE_COLUMNS: fixed Excel column order PA expects
- rows_to_xlsx(): list[dict] → bytes (in-memory XLSX)
- build_generic_row(): minimal fallback row for unmapped games
- _fake_personal_info(): placeholder personal data (first/last name, phone, etc.)
"""

from __future__ import annotations

import io
import random
import string
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# PA Excel column template — fixed order, must match PA bulk upload spec
# ---------------------------------------------------------------------------
# Note the double space in 'Login name  (Auto)' — this is intentional (PA API requirement).

TEMPLATE_COLUMNS: list[str] = [
    'Game',
    'Server',
    'Faction',
    'Listing Price',
    'Seller After-Sale Protection',
    'Offer Duration',
    'Cover image (PA hosted)',
    'Title',
    'Description',
    'Delivery Method',
    'Login name  (Auto)',       # double space — PA requirement
    'Password',
    'Character name',
    'Registration CD Key',
    'Parental password',
    'Security question',
    'Security question answer',
    'First name',
    'Last name',
    'Phone with area code',
    'Email',
    'City',
    'Country',
    'Birth Date',
    'Extra information',
    'Login name',               # manual delivery
    'Delivery guarantee',
    'Delivery info',
]


# ---------------------------------------------------------------------------
# XLSX builder
# ---------------------------------------------------------------------------

def rows_to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """Convert a list of Excel row dicts to an in-memory XLSX file.

    Each dict key must match a column in TEMPLATE_COLUMNS.
    Missing columns are filled with empty string.
    Extra keys not in TEMPLATE_COLUMNS are silently ignored.

    Returns raw XLSX bytes ready for multipart upload.
    """
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required for PA bulk upload. "
            "Add 'openpyxl' to requirements/base.txt and reinstall."
        ) from exc

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Offers'

    # Write header row
    ws.append(TEMPLATE_COLUMNS)

    # Write data rows in column order
    for row_dict in rows:
        row_values = [row_dict.get(col, '') for col in TEMPLATE_COLUMNS]
        ws.append(row_values)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Generic row builder (fallback for unmapped games)
# ---------------------------------------------------------------------------

def build_generic_row(
    *,
    game,
    owned_product,
    sources: dict,
    final_price: Decimal,
    sub_platform: str,
) -> dict[str, Any]:
    """Minimal PA row for games without a dedicated builder.

    Uses raw_data from sources['lzt'] when available.
    Fields like title/description will be generic — replace with real builders.
    """
    raw = sources.get('lzt', {}) or {}
    personal = _fake_personal_info()
    game_name = game.name if hasattr(game, 'name') else str(game)
    login = owned_product.login or ''
    email = _extract_email(raw) or f'{login}@example.com'

    return {
        'Game': game_name,
        'Server': sub_platform or 'PC',
        'Faction': '',
        'Listing Price': float(final_price),
        'Seller After-Sale Protection': 7,
        'Offer Duration': 30,
        'Cover image (PA hosted)': '',
        'Title': f'{game_name} Account',
        'Description': f'{game_name} account for sale.',
        'Delivery Method': 'Automatic',
        'Login name  (Auto)': login,
        'Password': owned_product.password or '',
        'Character name': '',
        'Registration CD Key': '',
        'Parental password': '',
        'Security question': '',
        'Security question answer': '',
        'First name': personal['first_name'],
        'Last name': personal['last_name'],
        'Phone with area code': personal['phone'],
        'Email': email,
        'City': personal['city'],
        'Country': personal['country'],
        'Birth Date': personal['birth_date'],
        'Extra information': '',
        'Login name': '',
        'Delivery guarantee': '',
        'Delivery info': '',
    }


# ---------------------------------------------------------------------------
# Shared field helpers
# ---------------------------------------------------------------------------

def _fake_personal_info() -> dict[str, str]:
    """Generate stable placeholder personal info for PA seller fields.

    These are used to fill required personal info fields in the PA offer form.
    In production, each store account has real seller info configured.
    TODO: Pull from store credential config instead of generating fake data.
    """
    first_names = ['James', 'John', 'Michael', 'David', 'Chris', 'Daniel', 'Matthew']
    last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller']
    cities = ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix']
    area_codes = ['212', '310', '773', '713', '602']

    idx = random.randint(0, len(first_names) - 1)
    area = random.choice(area_codes)
    phone_number = ''.join(random.choices(string.digits, k=7))

    return {
        'first_name': first_names[idx % len(first_names)],
        'last_name': last_names[idx % len(last_names)],
        'phone': f'{area}{phone_number}',
        'city': random.choice(cities),
        'country': 'United States',
        'birth_date': '1995/1/1',
    }


def _extract_email(raw: dict) -> str | None:
    """Extract email from LZT raw data if available and valid."""
    email = raw.get('email') or raw.get('login_email') or ''
    if email and '@' in email and 'unverified' not in email.lower():
        return email
    return None
