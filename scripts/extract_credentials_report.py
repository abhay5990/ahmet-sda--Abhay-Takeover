"""Extract credentials parse results from Orders and Listings (category=accounts, is_instant=True).

For each record, outputs:
  - id (DB id)
  - store_id (store_order_id or store_listing_id)
  - provider (gameboost / eldorado / playerauctions)
  - game (game name or empty)
  - credential_source (raw text that was fed to the parser)
  - parsed (ParsedCredentials as dict, empty dict if parsing failed/no source)

Writes 4 JSON files to tmp/credentials_report/:
  - orders_gameboost.json
  - orders_eldorado.json
  - listings_gameboost.json
  - listings_eldorado.json

PlayerAuctions uses direct field extraction (no parsing), so it's excluded.

Usage (from project root):
    python scripts/extract_credentials_report.py
"""

import json
import os
import sys
from dataclasses import asdict

# ── Bootstrap Django ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

from apps.orders.models import Order  # noqa: E402
from apps.listings.models import Listing  # noqa: E402
from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'credentials_report')
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Credential source extraction per provider ──────────────────────

def _extract_order_credential_sources(provider: str, raw: dict) -> list[tuple[str, str]]:
    """Return list of (source_label, credential_text) from order raw_data.

    Each tuple is a credential source that should be parsed independently.
    """
    sources = []

    if provider == 'gameboost':
        # 1. _credential_entries (API enrichment)
        entries = raw.get('_credential_entries') or []
        for i, entry in enumerate(entries):
            text = entry.get('credentials', '')
            if text:
                sources.append((f'credential_entry[{i}]', text))

        # 2. inline credentials string
        if not sources:
            creds = raw.get('credentials', '')
            if creds and isinstance(creds, str):
                sources.append(('inline_credentials', creds))

        # 3. delivery_instructions fallback
        if not sources:
            di = raw.get('delivery_instructions', '')
            if di:
                sources.append(('delivery_instructions', di))

    elif provider == 'eldorado':
        # accountDetails.secretDetails
        ad = raw.get('accountDetails') or {}
        secret = ad.get('secretDetails', '')
        if secret:
            sources.append(('accountDetails.secretDetails', secret))

    return sources


def _extract_listing_credential_sources(provider: str, raw: dict) -> list[tuple[str, str]]:
    """Return list of (source_label, credential_text) from listing raw_data."""
    sources = []

    if provider == 'gameboost':
        # 1. Legacy inline structured credentials
        creds = raw.get('credentials') or {}
        if isinstance(creds, dict) and creds.get('login') is not None:
            # Legacy format — build text representation for parsing comparison
            parts = []
            if creds.get('login'):
                parts.append(f"Login: {creds['login']}")
            if creds.get('password'):
                parts.append(f"Password: {creds['password']}")
            if creds.get('email_login'):
                parts.append(f"Email: {creds['email_login']}")
            if creds.get('email_password'):
                parts.append(f"Email Password: {creds['email_password']}")
            if parts:
                sources.append(('legacy_inline', '\n'.join(parts)))

        # 2. _credential_entries
        if not sources:
            entries = raw.get('_credential_entries') or []
            for i, entry in enumerate(entries):
                text = entry.get('credentials', '')
                if text:
                    sources.append((f'credential_entry[{i}]', text))

        # 3. delivery_instructions
        if not sources:
            di = raw.get('delivery_instructions', '')
            if di:
                sources.append(('delivery_instructions', di))

    elif provider == 'eldorado':
        # _credential_entries[].secretDetails
        entries = raw.get('_credential_entries') or []
        for i, entry in enumerate(entries):
            secret = entry.get('secretDetails', '')
            if secret:
                sources.append((f'credential_entry[{i}].secretDetails', secret))

    return sources


def _parse_and_build(source_label: str, text: str) -> dict:
    """Parse credential text and return result dict."""
    try:
        parsed = parse_credentials_text(text)
        return asdict(parsed)
    except Exception as e:
        return {'_parse_error': str(e)}


# ── Process Orders ──────────────────────────────────────────────────
print('Processing orders...')

SKIP_STATUSES = ('cancelled', 'refunded')

orders_qs = Order.objects.filter(
    product_category='accounts',
    is_instant=True,
).select_related('integration_account', 'game').exclude(
    raw_data__isnull=True,
).exclude(status__in=SKIP_STATUSES)

orders_by_provider = {}

for o in orders_qs.iterator():
    provider = o.integration_account.provider if o.integration_account else 'unknown'
    if provider not in ('gameboost', 'eldorado'):
        continue

    raw = o.raw_data or {}
    sources = _extract_order_credential_sources(provider, raw)

    game_name = o.game.name if o.game else ''

    if sources:
        for source_label, text in sources:
            record = {
                'id': o.id,
                'store_order_id': o.store_order_id,
                'provider': provider,
                'game': game_name,
                'credential_source': source_label,
                'raw_text': text,
                'parsed': _parse_and_build(source_label, text),
            }
            orders_by_provider.setdefault(provider, []).append(record)
    else:
        record = {
            'id': o.id,
            'store_order_id': o.store_order_id,
            'provider': provider,
            'game': game_name,
            'credential_source': 'none',
            'raw_text': '',
            'parsed': {},
        }
        orders_by_provider.setdefault(provider, []).append(record)

for provider, records in orders_by_provider.items():
    path = os.path.join(OUTPUT_DIR, f'orders_{provider}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False, default=str)
    parsed_count = sum(1 for r in records if r['parsed'] and r['parsed'].get('login'))
    empty_count = sum(1 for r in records if not r['parsed'] or not r['parsed'].get('login'))
    print(f'  Orders [{provider}]: {len(records)} total, {parsed_count} parsed, {empty_count} empty -> {path}')

# ── Process Listings ────────────────────────────────────────────────
print('Processing listings...')

listings_qs = Listing.objects.filter(
    product_category='accounts',
    is_instant=True,
).select_related('integration_account', 'game').exclude(raw_data__isnull=True)

listings_by_provider = {}

for l in listings_qs.iterator():
    provider = l.integration_account.provider if l.integration_account else 'unknown'
    if provider not in ('gameboost', 'eldorado'):
        continue

    raw = l.raw_data or {}
    sources = _extract_listing_credential_sources(provider, raw)

    game_name = l.game.name if l.game else ''

    if sources:
        for source_label, text in sources:
            record = {
                'id': l.id,
                'store_listing_id': l.store_listing_id,
                'provider': provider,
                'game': game_name,
                'credential_source': source_label,
                'raw_text': text,
                'parsed': _parse_and_build(source_label, text),
            }
            listings_by_provider.setdefault(provider, []).append(record)
    else:
        record = {
            'id': l.id,
            'store_listing_id': l.store_listing_id,
            'provider': provider,
            'game': game_name,
            'credential_source': 'none',
            'raw_text': '',
            'parsed': {},
        }
        listings_by_provider.setdefault(provider, []).append(record)

for provider, records in listings_by_provider.items():
    path = os.path.join(OUTPUT_DIR, f'listings_{provider}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False, default=str)
    parsed_count = sum(1 for r in records if r['parsed'] and r['parsed'].get('login'))
    empty_count = sum(1 for r in records if not r['parsed'] or not r['parsed'].get('login'))
    print(f'  Listings [{provider}]: {len(records)} total, {parsed_count} parsed, {empty_count} empty -> {path}')

# ── Summary ─────────────────────────────────────────────────────────
print(f'\nDosyalar: {OUTPUT_DIR}')
