"""Parse credentials from raw_payloads JSON files.

Filters: category=account, delivery=instant, status != cancelled/refunded
Then runs the credential parser on each record.

Usage (from project root):
    python scripts/parse_raw_payload_credentials.py
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

from apps.sync.services.shared.credentials import parse_credentials_text  # noqa: E402
from apps.inventory.models import GamePlatformMapping  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
RAW_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'raw_payloads')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'raw_credentials_parsed')
os.makedirs(OUTPUT_DIR, exist_ok=True)

SKIP_STATUSES = {'cancelled', 'canceled', 'refunded'}

# ── Game name mapping (platform + external_id -> game name) ────────
_GAME_CACHE: dict[tuple[str, str], str] = {}


def _build_game_cache():
    """Load GamePlatformMapping into a lookup dict."""
    for m in GamePlatformMapping.objects.select_related('game').all():
        key = (m.platform, str(m.external_id))
        _GAME_CACHE[key] = m.game.name if m.game else ''


_build_game_cache()
print(f'Game cache loaded: {len(_GAME_CACHE)} mappings')


# ── Provider detection ──────────────────────────────────────────────

def detect_provider(raw: dict) -> str:
    offer_id = raw.get('offerId', '')
    if isinstance(offer_id, str) and '-' in offer_id:
        return 'eldorado'
    if 'delivery_instructions' in raw or 'credentials' in raw:
        return 'gameboost'
    if 'order_info' in raw or 'orderInfo' in raw:
        return 'playerauctions'
    if isinstance(raw.get('id'), int):
        return 'gameboost'
    return 'unknown'


# ── Filter checks ──────────────────────────────────────────────────

def is_instant_order(provider: str, raw: dict) -> bool:
    if provider == 'eldorado':
        return raw.get('guaranteedDeliveryTime') == 'Instant'
    elif provider == 'gameboost':
        return raw.get('is_instant', False) is True
    elif provider == 'playerauctions':
        oi = raw.get('order_info') or raw.get('orderInfo') or {}
        offer_info = oi.get('offerInfo') or oi.get('offer_info') or {}
        return (offer_info.get('unit') or '').strip().lower() == 'instant'
    return False


def is_account_category(provider: str, raw: dict) -> bool:
    if provider == 'eldorado':
        return raw.get('category') == 'Account'
    elif provider == 'gameboost':
        cat = raw.get('product_category') or raw.get('category') or ''
        return cat.lower() in ('accounts', 'account')
    elif provider == 'playerauctions':
        pt = raw.get('product_type') or ''
        return pt.lower() in ('game accounts', 'accounts', 'account')
    return False


def is_cancelled_or_refunded(db_status: str) -> bool:
    return db_status.lower() in SKIP_STATUSES


# ── Credential extraction ──────────────────────────────────────────

def extract_credential_text(provider: str, raw: dict) -> list[tuple[str, str]]:
    """Return list of (source_label, credential_text)."""
    sources = []

    if provider == 'eldorado':
        ad = raw.get('accountDetails') or {}
        secret = ad.get('secretDetails', '')
        if secret:
            sources.append(('accountDetails.secretDetails', secret))

    elif provider == 'gameboost':
        # 1. _credential_entries
        entries = raw.get('_credential_entries') or []
        for i, entry in enumerate(entries):
            text = entry.get('credentials', '')
            if text:
                sources.append((f'credential_entry[{i}]', text))
        # 2. inline credentials
        if not sources:
            creds = raw.get('credentials', '')
            if creds and isinstance(creds, str):
                sources.append(('inline_credentials', creds))
        # 3. delivery_instructions
        if not sources:
            di = raw.get('delivery_instructions', '')
            if di:
                sources.append(('delivery_instructions', di))

    elif provider == 'playerauctions':
        oi = raw.get('order_info') or raw.get('orderInfo') or {}
        login = oi.get('loginName') or oi.get('login_name') or ''
        if login:
            sources.append(('orderInfo.loginName', login))

    return sources


def _resolve_game_id(platform: str, game_id) -> str:
    """Resolve game_id to game name via cache, fallback to 'platform#id'."""
    if not game_id:
        return ''
    name = _GAME_CACHE.get((platform, str(game_id)))
    if name:
        return name
    return f'{platform}#{game_id}'


def extract_order_game(provider: str, raw: dict) -> str:
    """Resolve game name from order raw_data."""
    if provider == 'eldorado':
        ood = raw.get('orderOfferDetails') or {}
        return _resolve_game_id('eldorado', ood.get('gameId'))
    elif provider == 'gameboost':
        game = raw.get('game') or {}
        if isinstance(game, dict):
            if game.get('name'):
                return game['name']
            return _resolve_game_id('gameboost', game.get('id'))
    elif provider == 'playerauctions':
        oi = raw.get('order_info') or raw.get('orderInfo') or {}
        market = oi.get('market') or {}
        return market.get('title') or ''
    return ''


def extract_listing_game(provider: str, raw: dict) -> str:
    """Resolve game name from listing raw_data."""
    if provider == 'eldorado':
        return _resolve_game_id('eldorado', raw.get('gameId'))
    elif provider == 'gameboost':
        game = raw.get('game') or {}
        if isinstance(game, dict):
            if game.get('name'):
                return game['name']
            return _resolve_game_id('gameboost', game.get('id'))
    return ''


# ── Process orders ──────────────────────────────────────────────────
print('Loading orders...')
with open(os.path.join(RAW_DIR, 'orders_raw.json'), encoding='utf-8') as f:
    orders = json.load(f)

print(f'Total orders: {len(orders)}')

results_by_provider = {}
stats = {'total': 0, 'filtered_in': 0, 'skipped_cancelled': 0}

# NOTE: raw_payloads are already filtered from DB as category=accounts, is_instant=True
# So we only need to filter out cancelled/refunded orders here
for o in orders:
    stats['total'] += 1
    raw = o.get('raw_data') or {}
    db_status = o.get('status', '')
    provider = detect_provider(raw)

    if is_cancelled_or_refunded(db_status):
        stats['skipped_cancelled'] += 1
        continue

    stats['filtered_in'] += 1
    sources = extract_credential_text(provider, raw)
    game = extract_order_game(provider, raw)

    if sources:
        for source_label, text in sources:
            try:
                parsed = asdict(parse_credentials_text(text))
            except Exception as e:
                parsed = {'_parse_error': str(e)}

            record = {
                'id': o['id'],
                'store_order_id': o['store_order_id'],
                'provider': provider,
                'status': db_status,
                'game': game,
                'credential_source': source_label,
                'raw_text': text,
                'parsed': parsed,
            }
            results_by_provider.setdefault(provider, []).append(record)
    else:
        record = {
            'id': o['id'],
            'store_order_id': o['store_order_id'],
            'provider': provider,
            'status': db_status,
            'game': game,
            'credential_source': 'none',
            'raw_text': '',
            'parsed': {},
        }
        results_by_provider.setdefault(provider, []).append(record)

print(f'Filter stats: {stats}')

for provider, records in results_by_provider.items():
    path = os.path.join(OUTPUT_DIR, f'orders_{provider}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False, default=str)
    ok = sum(1 for r in records if r['parsed'] and r['parsed'].get('login') and r['parsed'].get('password'))
    no_pass = sum(1 for r in records if r['parsed'] and r['parsed'].get('login') and not r['parsed'].get('password'))
    empty = sum(1 for r in records if not r['parsed'] or not r['parsed'].get('login'))
    print(f'  {provider}: {len(records)} total | {ok} OK | {no_pass} no_password | {empty} empty -> {path}')

# ── Process listings ────────────────────────────────────────────────
print('\nLoading listings...')
with open(os.path.join(RAW_DIR, 'listings_raw.json'), encoding='utf-8') as f:
    listings = json.load(f)

print(f'Total listings: {len(listings)}')


def detect_listing_provider(raw: dict) -> str:
    offer_id = raw.get('id', '')
    if isinstance(offer_id, str) and '-' in offer_id:
        return 'eldorado'
    if 'delivery_instructions' in raw or 'credentials' in raw:
        return 'gameboost'
    if isinstance(raw.get('id'), int):
        return 'gameboost'
    return 'unknown'


def is_listing_account(provider: str, raw: dict) -> bool:
    if provider == 'eldorado':
        return raw.get('category') == 'Account'
    elif provider == 'gameboost':
        cat = raw.get('product_category') or raw.get('category') or ''
        return cat.lower() in ('accounts', 'account')
    return False


def is_listing_instant(provider: str, raw: dict) -> bool:
    if provider == 'eldorado':
        return raw.get('guaranteedDeliveryTime') == 'Instant'
    elif provider == 'gameboost':
        return raw.get('is_instant', False) is True
    return False


def extract_listing_credential_text(provider: str, raw: dict) -> list[tuple[str, str]]:
    sources = []
    if provider == 'eldorado':
        entries = raw.get('_credential_entries') or []
        for i, entry in enumerate(entries):
            secret = entry.get('secretDetails', '')
            if secret:
                sources.append((f'credential_entry[{i}].secretDetails', secret))
    elif provider == 'gameboost':
        creds = raw.get('credentials') or {}
        if isinstance(creds, dict) and creds.get('login') is not None:
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
        if not sources:
            entries = raw.get('_credential_entries') or []
            for i, entry in enumerate(entries):
                text = entry.get('credentials', '')
                if text:
                    sources.append((f'credential_entry[{i}]', text))
        if not sources:
            di = raw.get('delivery_instructions', '')
            if di:
                sources.append(('delivery_instructions', di))
    return sources


listing_results = {}
l_stats = {'total': 0, 'filtered_in': 0}

# NOTE: raw_payloads are already filtered from DB as category=accounts, is_instant=True
for l in listings:
    l_stats['total'] += 1
    raw = l.get('raw_data') or {}
    provider = detect_listing_provider(raw)

    l_stats['filtered_in'] += 1
    sources = extract_listing_credential_text(provider, raw)
    game = extract_listing_game(provider, raw)

    if sources:
        for source_label, text in sources:
            try:
                parsed = asdict(parse_credentials_text(text))
            except Exception as e:
                parsed = {'_parse_error': str(e)}
            record = {
                'id': l['id'],
                'store_listing_id': l['store_listing_id'],
                'provider': provider,
                'status': l.get('status', ''),
                'game': game,
                'credential_source': source_label,
                'raw_text': text,
                'parsed': parsed,
            }
            listing_results.setdefault(provider, []).append(record)
    else:
        record = {
            'id': l['id'],
            'store_listing_id': l['store_listing_id'],
            'provider': provider,
            'status': l.get('status', ''),
            'game': game,
            'credential_source': 'none',
            'raw_text': '',
            'parsed': {},
        }
        listing_results.setdefault(provider, []).append(record)

print(f'Filter stats: {l_stats}')

for provider, records in listing_results.items():
    path = os.path.join(OUTPUT_DIR, f'listings_{provider}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False, default=str)
    ok = sum(1 for r in records if r['parsed'] and r['parsed'].get('login') and r['parsed'].get('password'))
    no_pass = sum(1 for r in records if r['parsed'] and r['parsed'].get('login') and not r['parsed'].get('password'))
    empty = sum(1 for r in records if not r['parsed'] or not r['parsed'].get('login'))
    print(f'  {provider}: {len(records)} total | {ok} OK | {no_pass} no_password | {empty} empty -> {path}')

print(f'\nDosyalar: {OUTPUT_DIR}')
