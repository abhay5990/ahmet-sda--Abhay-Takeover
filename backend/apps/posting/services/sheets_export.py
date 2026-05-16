"""Google Sheets export for PostingJob detail.

Reuses the existing SheetsExportService + GoogleSheetsService infrastructure
from inventory. Exports login-grouped job data with per-marketplace status columns.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.inventory.services.sheets_export import (
    SheetsExportService,
    extract_spreadsheet_id,
    get_google_sheets_credential,
)
from apps.posting.models import PostingJob

logger = logging.getLogger(__name__)

# Marketplace display names (order matters for column output)
MARKETPLACE_DISPLAY = {
    'eldorado': 'Eldorado',
    'gameboost': 'GameBoost',
    'g2g': 'G2G',
    'playerauctions': 'PlayerAuctions',
}


def export_job_to_sheet(
    job: PostingJob,
    spreadsheet_id: str,
    sheet_name: str,
    columns: list[str],
    store_keys: list[str],
) -> int:
    """Export a PostingJob's grouped data to Google Sheets.

    Args:
        job: The PostingJob to export.
        spreadsheet_id: Google Sheets ID or full URL.
        sheet_name: Target worksheet name.
        columns: Ordered list of column keys to include.
        store_keys: Which store (IntegrationAccount) IDs to include as columns.

    Returns the number of data rows written (excluding header).
    """
    credential = get_google_sheets_credential()
    if not credential:
        raise ValueError('No active Google Sheets credential configured.')

    items = (
        job.items
        .select_related('owned_product', 'store', 'listing')
        .order_by('id')
    )

    # Build grouped data
    from collections import OrderedDict
    grouped: OrderedDict[str, dict] = OrderedDict()

    for item in items:
        login = item.login
        if login not in grouped:
            op = item.owned_product
            grouped[login] = {
                'login': login,
                'ref_key': op.ref_key if op else '',
                'password': op.password if op else '',
                'email': op.email if op else '',
                'email_password': op.email_password if op else '',
                'purchase_price': float(op.price) if op and op.price else '',
                'currency': op.currency if op else 'USD',
                'updated_at': item.updated_at,
                'marketplaces': {},
            }
        if item.updated_at and item.updated_at > grouped[login]['updated_at']:
            grouped[login]['updated_at'] = item.updated_at

        store_key = str(item.store_id)
        grouped[login]['marketplaces'][store_key] = {
            'status': item.status,
            'error': item.error_message,
            'sale_price': float(item.listing.price) if item.listing else '',
            'sale_currency': item.listing.currency if item.listing else '',
            'offer_id': item.listing.store_listing_id if item.listing else '',
            'offer_title': item.listing.title if item.listing else '',
        }

    # Column accessors
    base_accessors: dict[str, tuple[str, Any]] = {
        'index': ('#', lambda i, _r: i + 1),
        'ref_key': ('Ref', lambda _i, r: r['ref_key']),
        'updated_at': ('Time', lambda _i, r: r['updated_at'].strftime('%Y-%m-%d %H:%M') if r['updated_at'] else ''),
        'purchase_price': ('Purchase Price', lambda _i, r: r['purchase_price']),
        'login': ('Login', lambda _i, r: r['login']),
        'password': ('Password', lambda _i, r: r['password']),
        'email': ('Email', lambda _i, r: r['email']),
        'email_password': ('Email Password', lambda _i, r: r['email_password']),
    }

    # Build header + rows
    header: list[str] = []
    accessors: list[Any] = []

    for col_key in columns:
        if col_key in base_accessors:
            label, accessor = base_accessors[col_key]
            header.append(label)
            accessors.append(('base', accessor))
        elif col_key == 'sale_price':
            header.append('Sale Price')
            # Use the first marketplace's sale price
            accessors.append(('sale_price', None))
        elif col_key == 'offer_title':
            header.append('Offer Title')
            accessors.append(('offer_title', None))

    # Build store_id -> display name mapping
    from apps.integrations.models import IntegrationAccount
    store_ids = [int(k) for k in store_keys if k.isdigit()]
    store_display = {}
    if store_ids:
        for acct in IntegrationAccount.objects.filter(id__in=store_ids):
            mp_label = MARKETPLACE_DISPLAY.get(acct.provider, acct.provider)
            store_display[str(acct.id)] = f'{mp_label} ({acct.name})'

    # Add store columns
    for sk in store_keys:
        name = store_display.get(sk, sk)
        header.append(f'{name} Status')
        header.append(f'{name} Offer ID')
        header.append(f'{name} Error')

    rows: list[list[Any]] = [header]
    for idx, row_data in enumerate(grouped.values()):
        row: list[Any] = []
        for acc_type, accessor in accessors:
            if acc_type == 'base':
                row.append(accessor(idx, row_data))
            elif acc_type == 'sale_price':
                # First available sale price
                for sk in store_keys:
                    mp_data = row_data['marketplaces'].get(sk, {})
                    if mp_data.get('sale_price'):
                        row.append(mp_data['sale_price'])
                        break
                else:
                    row.append('')
            elif acc_type == 'offer_title':
                for sk in store_keys:
                    mp_data = row_data['marketplaces'].get(sk, {})
                    if mp_data.get('offer_title'):
                        row.append(mp_data['offer_title'])
                        break
                else:
                    row.append('')

        # Store columns
        for sk in store_keys:
            mp_data = row_data['marketplaces'].get(sk, {})
            row.append(mp_data.get('status', ''))
            row.append(mp_data.get('offer_id', ''))
            row.append(mp_data.get('error', ''))

        rows.append(row)

    sid = extract_spreadsheet_id(spreadsheet_id)
    svc = SheetsExportService.from_credential(credential)
    written = svc._client.write_to_sheet(sid, sheet_name, rows)
    logger.info("Exported job #%d: %d rows to sheet '%s'", job.pk, written - 1, sheet_name)
    return written - 1
