"""Google Sheets export service for OwnedProduct.

Exports a filtered OwnedProduct queryset to a Google Sheets worksheet.
Column definitions are extensible — adding new columns requires only
appending to ALL_COLUMNS.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from django.db.models import QuerySet

from apps.integrations.models import ServiceCredential, ServiceType
from apps.integrations.services.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ColumnDef:
    key: str
    header: str
    accessor: Callable[[Any], str]
    is_extra: bool = False


def _safe(val: Any) -> str:
    if val is None:
        return ''
    return str(val)


def _price(val: Any) -> float | str:
    """Return price as a float so Google Sheets treats it as a number."""
    if val is None:
        return ''
    try:
        return float(val)
    except (TypeError, ValueError):
        return str(val)


# Ordered column registry — is_extra columns are included only when selected.
# The order here defines the column order in the exported sheet.
ALL_COLUMNS: list[ColumnDef] = [
    ColumnDef('login', 'Login', lambda p: p.login),
    ColumnDef('password', 'Password', lambda p: _safe(p.password), is_extra=True),
    ColumnDef('email', 'Email', lambda p: _safe(p.email), is_extra=True),
    ColumnDef('email_password', 'Email Password', lambda p: _safe(p.email_password), is_extra=True),
    ColumnDef('email_login_link', 'Email Login Link', lambda p: _safe(p.email_login_link), is_extra=True),
    ColumnDef('security_email', 'Security Email', lambda p: _safe(p.security_email), is_extra=True),
    ColumnDef('security_email_password', 'Security Email Password', lambda p: _safe(p.security_email_password), is_extra=True),
    ColumnDef('game', 'Game', lambda p: _safe(p.game.name if p.game else None)),
    ColumnDef('category', 'Category', lambda p: _safe(p.category.title if p.category else None)),
    ColumnDef('price', 'Price', lambda p: _price(p.price)),
    ColumnDef('currency', 'Currency', lambda p: p.currency),
    ColumnDef('status', 'Status', lambda p: p.get_status_display()),
    ColumnDef('source', 'Source', lambda p: _safe(p.source_account.name if p.source_account else None)),
    ColumnDef('source_product_id', 'Source Product ID', lambda p: _safe(p.source_product_id), is_extra=True),
    ColumnDef('purchased_at', 'Purchased', lambda p: p.purchased_at.strftime('%Y-%m-%d %H:%M') if p.purchased_at else '', is_extra=True),
    ColumnDef('created_at', 'Created', lambda p: p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else ''),
]

ALL_EXTRA_KEYS = {c.key for c in ALL_COLUMNS if c.is_extra}

_SPREADSHEET_ID_RE = re.compile(r'/spreadsheets/d/([a-zA-Z0-9_-]+)')


def extract_spreadsheet_id(raw: str) -> str:
    """Accept a full Google Sheets URL or a bare spreadsheet ID."""
    raw = raw.strip()
    m = _SPREADSHEET_ID_RE.search(raw)
    if m:
        return m.group(1)
    return raw


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SheetsExportService:
    """Exports OwnedProduct queryset → Google Sheets worksheet."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_credential(cls, credential: ServiceCredential) -> SheetsExportService:
        client = GoogleSheetsService.build_client(credential)
        return cls(client)

    def export(
        self,
        queryset: QuerySet,
        spreadsheet_id: str,
        sheet_name: str,
        extra_fields: list[str] | None = None,
        limit: int = 0,
    ) -> int:
        """Export queryset to a Google Sheet.

        Args:
            limit: Max rows to export. 0 = all.

        Returns the number of data rows written (excluding header).
        """
        extra_set = set(extra_fields) if extra_fields else set()
        columns = [c for c in ALL_COLUMNS if not c.is_extra or c.key in extra_set]

        # Determine which fields to NOT defer
        needs_encrypted = any(c.key in ('password', 'email_password', 'security_email_password') for c in columns)
        if needs_encrypted:
            queryset = queryset.defer('raw_data')
        else:
            queryset = queryset.defer(
                'password', 'email_password', 'security_email_password',
                'password_hash', 'raw_data',
            )

        if limit > 0:
            queryset = queryset[:limit]

        # Build rows
        header = [c.header for c in columns]
        rows: list[list[Any]] = [header]
        for product in queryset.iterator(chunk_size=500):
            rows.append([c.accessor(product) for c in columns])

        sid = extract_spreadsheet_id(spreadsheet_id)
        written = self._client.write_to_sheet(sid, sheet_name, rows)
        logger.info("Exported %d rows to sheet '%s' in %s", written - 1, sheet_name, sid)
        return written - 1  # exclude header


def get_google_sheets_credential() -> ServiceCredential | None:
    """Return the first active google-sheets ServiceCredential, or None."""
    return (
        ServiceCredential.objects
        .filter(service_type=ServiceType.GOOGLE_SHEETS, is_active=True)
        .first()
    )
