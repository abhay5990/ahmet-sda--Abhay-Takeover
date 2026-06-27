"""Manual posting API endpoints — Google Sheets integration for Fortnite."""

from __future__ import annotations

import json
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from apps.integrations.models import ServiceCredential, ServiceType
from apps.posting.api.media_override import mark_image_override_used

logger = logging.getLogger(__name__)

_DEFAULT_SHEET_NAME = 'FORTNITE MANUAL'

_HEADERS = [
    'Mail',
    'Mail PW',
    'Epic PW',
    'Price',
    'Sales Price',
    'Platform',
    'Title',
    'Items',
    'Images',
]


def _get_sheets_client():
    """Get the active Google Sheets client from ServiceCredential."""
    from apps.integrations.services.google_sheets import GoogleSheetsService

    credential = ServiceCredential.objects.filter(
        service_type=ServiceType.GOOGLE_SHEETS,
        is_active=True,
    ).first()
    if not credential:
        return None
    return GoogleSheetsService.build_client(credential)


@login_required
@require_POST
def open_sheet(request):
    """Prepare a worksheet inside a user-provided spreadsheet.

    Expects JSON body: {spreadsheet_id: str, sheet_name?: str}
    Creates the worksheet if missing, writes headers, returns the URL.
    """
    client = _get_sheets_client()
    if not client:
        return JsonResponse(
            {'error': 'Google Sheets service not configured. Add a google-sheets ServiceCredential.'},
            status=400,
        )

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    spreadsheet_id = (body.get('spreadsheet_id') or '').strip()
    if not spreadsheet_id:
        return JsonResponse({'error': 'spreadsheet_id is required.'}, status=400)

    sheet_name = (body.get('sheet_name') or '').strip() or _DEFAULT_SHEET_NAME

    try:
        ws = client.get_or_create_worksheet(spreadsheet_id, sheet_name, rows=500, cols=len(_HEADERS))

        # Check existing data (beyond header row)
        all_values = ws.get_all_values()
        has_data = len(all_values) > 1

        # Write headers if missing or different
        existing_header = all_values[0] if all_values else []
        if existing_header != _HEADERS:
            if has_data:
                # Sheet has data with different headers — warn but still write
                ws.update([_HEADERS], 'A1', value_input_option='USER_ENTERED')
            else:
                ws.update([_HEADERS], 'A1', value_input_option='USER_ENTERED')

        sheet_url = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={ws.id}'

        message = 'Sheet ready — headers written.' if not has_data else f'Sheet ready — {len(all_values) - 1} existing data row(s) found.'

        return JsonResponse({
            'url': sheet_url,
            'sheet_name': sheet_name,
            'spreadsheet_id': spreadsheet_id,
            'has_data': has_data,
            'message': message,
        })
    except Exception as exc:
        logger.exception("Failed to prepare Fortnite manual sheet")
        return JsonResponse({'error': f'Google Sheets error: {exc}'}, status=500)


@login_required
@require_GET
def fetch_accounts(request):
    """Read accounts from a user-specified worksheet.

    Query params: spreadsheet_id (required), sheet_name (optional).
    """
    client = _get_sheets_client()
    if not client:
        return JsonResponse({'error': 'Google Sheets service not configured.'}, status=400)

    spreadsheet_id = (request.GET.get('spreadsheet_id') or '').strip()
    if not spreadsheet_id:
        return JsonResponse({'error': 'spreadsheet_id is required.'}, status=400)

    sheet_name = (request.GET.get('sheet_name') or '').strip() or _DEFAULT_SHEET_NAME

    try:
        rows = client.read_sheet(spreadsheet_id, sheet_name)
    except Exception as exc:
        logger.exception("Failed to read Fortnite manual sheet")
        return JsonResponse({'error': f'Google Sheets error: {exc}'}, status=500)

    if not rows or len(rows) < 2:
        return JsonResponse({'error': 'Sheet is empty (no data rows).'}, status=400)

    # Skip header row
    header = rows[0]
    data_rows = rows[1:]

    accounts = []
    errors = []

    for i, row in enumerate(data_rows, start=2):
        # Pad row to header length
        row = row + [''] * (len(_HEADERS) - len(row))

        mail = row[0].strip()
        mail_pw = row[1].strip()
        epic_pw = row[2].strip()
        price = row[3].strip()
        sales_price = row[4].strip()
        platform_raw = row[5].strip()
        title = row[6].strip()
        items_desc = row[7].strip()
        images = row[8].strip()

        # Validation
        if not mail:
            continue  # Skip empty rows

        if not mail_pw:
            errors.append(f'Row {i}: Mail PW is required')
            continue

        if not sales_price:
            errors.append(f'Row {i}: Sales Price is required')
            continue

        if not title:
            errors.append(f'Row {i}: Title is required')
            continue

        # Parse sales price
        try:
            sales_price_val = float(sales_price.replace(',', '.'))
        except ValueError:
            errors.append(f'Row {i}: Invalid Sales Price "{sales_price}"')
            continue

        # Parse platform
        platforms = _parse_platform(platform_raw, title)

        # Update title with platforms if platform column overrides
        final_title = _apply_platform_to_title(title, platforms, platform_raw)

        # Parse items/description
        parsed_items = _parse_items_description(items_desc)

        # Epic PW fallback
        epic_password = epic_pw if epic_pw else mail_pw

        account = {
            'row': i,
            'mail': mail,
            'mail_pw': mail_pw,
            'epic_pw': epic_password,
            'price': price,
            'sales_price': sales_price_val,
            'platforms': platforms,
            'title': final_title,
            'items_raw': items_desc,
            'parsed_items': parsed_items,
            'images': images,
        }
        accounts.append(account)

    return JsonResponse({
        'accounts': accounts,
        'total': len(accounts),
        'errors': errors,
    })


# --- Platform parsing ---

_PLATFORM_KEYWORDS = {
    'psn': 'PSN',
    'ps': 'PSN',
    'playstation': 'PSN',
    'xbox': 'XBOX',
    'pc': 'PC',
}


def _parse_platform(platform_raw: str, title: str) -> list[str]:
    """Parse platform from the platform column or title.

    Rules:
    - Empty/no/blank → parse from title
    - 'linkable' → all platforms (PC, PSN, XBOX)
    - Otherwise extract mentioned platforms, PC always included
    """
    normalized = platform_raw.lower().strip()

    # Empty or "no" → parse from title
    if not normalized or normalized == 'no':
        return _parse_platform_from_title(title)

    # Linkable = all platforms
    if normalized == 'linkable':
        return ['PC', 'PSN', 'XBOX']

    # Extract platforms from the raw value
    platforms = set()
    for keyword, platform in _PLATFORM_KEYWORDS.items():
        if keyword in normalized:
            platforms.add(platform)

    # PC is always included as default
    platforms.add('PC')

    # Return in consistent order
    return _sort_platforms(list(platforms))


def _parse_platform_from_title(title: str) -> list[str]:
    """Extract platforms from title brackets like [PC], [PC/PSN/XBOX]."""
    match = re.search(r'\[([^\]]+)\]', title)
    if not match:
        return ['PC']  # Default

    bracket_content = match.group(1).lower()
    platforms = set()
    for keyword, platform in _PLATFORM_KEYWORDS.items():
        if keyword in bracket_content:
            platforms.add(platform)

    platforms.add('PC')  # PC always included
    return _sort_platforms(list(platforms))


def _sort_platforms(platforms: list[str]) -> list[str]:
    """Sort platforms in consistent order: PC, PSN, XBOX."""
    order = {'PC': 0, 'PSN': 1, 'XBOX': 2}
    return sorted(platforms, key=lambda p: order.get(p, 99))


def _apply_platform_to_title(title: str, platforms: list[str], platform_raw: str) -> str:
    """Update title prefix with platforms if platform column is specified.

    If platform column is empty/no, title stays as-is.
    If platform column has value, replace or prepend [PC/PSN/XBOX] format.
    """
    normalized = platform_raw.lower().strip()
    if not normalized or normalized == 'no':
        return title  # Don't modify title

    # Build platform prefix
    platform_str = '/'.join(platforms)
    prefix = f'[{platform_str}]'

    # Remove existing bracket prefix from title
    title_clean = re.sub(r'^\[[^\]]*\]\s*', '', title)

    return f'{prefix} {title_clean}'


# --- Items/Description parsing ---

_ITEM_PATTERNS = {
    'outfits': re.compile(r'outfits?\s*:\s*(\d+)', re.IGNORECASE),
    'backpacks': re.compile(r'backpacks?\s*:\s*(\d+)', re.IGNORECASE),
    'pickaxes': re.compile(r'pickaxes?\s*:\s*(\d+)', re.IGNORECASE),
    'emotes': re.compile(r'(?:dances?|emotes?)\s*:\s*(\d+)', re.IGNORECASE),
    'gliders': re.compile(r'gliders?\s*:\s*(\d+)', re.IGNORECASE),
    'wraps': re.compile(r'wraps?\s*:\s*(\d+)', re.IGNORECASE),
    'banners': re.compile(r'banners?\s*:\s*(\d+)', re.IGNORECASE),
    'sprays': re.compile(r'sprays?\s*:\s*(\d+)', re.IGNORECASE),
    'exclusives': re.compile(r'exclusives?\s*:\s*(\d+)', re.IGNORECASE),
}

_LEVEL_PATTERN = re.compile(r'account\s*level\s*:\s*(\d+)', re.IGNORECASE)
_WINS_PATTERN = re.compile(r'total\s*wins?\s*:\s*(\d+)', re.IGNORECASE)


def _parse_items_description(text: str) -> dict:
    """Parse item counts and metadata from items/description text.

    Handles both formats:
    1. Simple items list: "Outfits: 20\nBackpacks: 19..."
    2. Full description with stats: "Account Level: 2949\n...Outfits: 107..."

    Returns dict with parsed counts and flags.
    """
    result = {
        'outfits': 0,
        'backpacks': 0,
        'pickaxes': 0,
        'emotes': 0,
        'gliders': 0,
        'wraps': 0,
        'banners': 0,
        'sprays': 0,
        'exclusives': 0,
        'level': 500,  # Default like old system
        'wins': 0,
        'is_full_description': False,
    }

    if not text:
        return result

    # Parse item counts
    for key, pattern in _ITEM_PATTERNS.items():
        match = pattern.search(text)
        if match:
            result[key] = int(match.group(1))

    # Parse level (only from full description)
    level_match = _LEVEL_PATTERN.search(text)
    if level_match:
        result['level'] = int(level_match.group(1))

    # Parse wins
    wins_match = _WINS_PATTERN.search(text)
    if wins_match:
        result['wins'] = int(wins_match.group(1))

    # Detect if this is a full description (has separators or Account Statistics)
    if '━' in text or 'Account Statistics' in text or 'Account Level' in text:
        result['is_full_description'] = True

    return result


# --- Sheet Job Creation (called from stock.py) ---

def _create_sheet_job(body: dict, game, stores: list, job_settings: dict):
    """Create a posting job from Google Sheet accounts (Fortnite manual).

    Each account has its own title, description, price, and platforms.
    Creates OwnedProducts and PostingJobItems accordingly.
    """
    import hashlib
    import threading
    import uuid
    from decimal import Decimal

    from apps.inventory.models import OwnedProduct
    from apps.posting.models import PostingJob, PostingJobItem

    accounts = body.get('accounts', [])
    if not accounts:
        return JsonResponse({'error': 'No accounts provided'}, status=400)

    if not game.category_id:
        return JsonResponse({'error': 'Game has no category assigned'}, status=400)

    # Determine if all accounts have sales_price (fixed-price mode)
    # vs. no sales_price (multiplier mode, pipeline calculates final price).
    has_sales_price = body.get('has_sales_price', False)

    owned_products = []
    for acc in accounts:
        mail = acc.get('mail', '').strip()
        mail_pw = acc.get('mail_pw', '').strip()
        epic_pw = acc.get('epic_pw', mail_pw).strip()
        sales_price = acc.get('sales_price', 0)
        price_raw = acc.get('price', '').strip() if isinstance(acc.get('price'), str) else acc.get('price', '')
        platforms = acc.get('platforms', ['PC'])
        title = acc.get('title', '')
        items_raw = acc.get('items_raw', '')
        parsed_items = acc.get('parsed_items', {})
        images = acc.get('images', '')

        if not mail or not mail_pw:
            continue

        login = mail.lower().strip()
        password = epic_pw or mail_pw

        # Parse price column (purchased cost)
        try:
            price_val = float(str(price_raw).replace(',', '.')) if price_raw else 0.0
        except (ValueError, TypeError):
            price_val = 0.0

        # Determine pipeline price and purchased price
        if has_sales_price and sales_price:
            # Fixed-price mode: sales_price is the final listing price
            pipeline_price = float(sales_price)
            # Purchased price: Price column if available, otherwise sales_price / 2
            purchased_price = price_val if price_val > 0 else float(sales_price) / 2
        else:
            # Multiplier mode: price goes through pipeline with user's multiplier
            pipeline_price = price_val if price_val > 0 else float(sales_price or 0)
            purchased_price = pipeline_price

        # Build raw_data for the pipeline
        raw_data = {
            'source': 'manual',
            'game': 'fortnite',
            'main_platform': platforms[0] if platforms else 'PC',
            'platforms': platforms,
            'price': pipeline_price,
            'loginData': {
                'login': login,
                'password': password,
            },
            'emailLoginData': {
                'login': login,
                'password': mail_pw,
            },
            'title': title,
            'description': items_raw,
            'parsed_items': parsed_items,
            'images': images,
            'level': parsed_items.get('level', 500),
            'wins': parsed_items.get('wins', 0),
            'item_id': f'manual-fn-{uuid.uuid4().hex[:12]}',
        }

        owned, _ = OwnedProduct.objects.update_or_create(
            category=game.category,
            login=login,
            defaults={
                'password': password,
                'password_hash': hashlib.sha256(password.encode()).hexdigest(),
                'email': login,
                'email_password': mail_pw,
                'game': game,
                'status': 'draft',
                'price': Decimal(str(purchased_price)),
                'currency': 'USD',
                'source_account': None,
                'raw_data': raw_data,
            },
        )
        owned_products.append(owned)

    if not owned_products:
        return JsonResponse({'error': 'No valid accounts to post'}, status=400)

    # All accounts go to all stores (cross-platform)
    items_data = []
    for owned in owned_products:
        for store in stores:
            items_data.append((owned.login, owned, store))

    # Force multiplier=1.0 only when sales_price is set (price is already final)
    if has_sales_price:
        for store in stores:
            store_key = store.slug
            if store_key not in job_settings:
                job_settings[store_key] = {}
            job_settings[store_key]['multiplier_low'] = '1.00'
            job_settings[store_key]['multiplier_mid'] = '1.00'
            job_settings[store_key]['multiplier_high'] = '1.00'

    # Mark sheet source in job settings
    job_settings['_manual'] = {
        'source_type': 'sheet',
        'game': 'fortnite',
    }

    total = len(items_data)
    job = PostingJob.objects.create(
        game=game,
        source_account=None,
        settings=job_settings,
        total_count=total,
    )
    mark_image_override_used(job_settings)

    items = []
    for login, owned, store in items_data:
        items.append(PostingJobItem(
            job=job,
            login=login,
            owned_product=owned,
            store=store,
            marketplace=store.provider,
        ))
    PostingJobItem.objects.bulk_create(items)

    # Launch job in background thread
    from apps.posting.api.stock import _launch_job
    return _launch_job(job, total)
