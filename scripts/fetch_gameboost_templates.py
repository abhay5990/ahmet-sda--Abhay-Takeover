"""Fetch + generate Gameboost templates for every game, all categories at once.

One-shot pipeline. Running this script:

  1. Finds the first working Gameboost account in the DB (active account +
     active credential carrying an api_key).
  2. GET /v2/games?sort=name to list ALL games and their services
     (raw list saved to tmp/gameboost/games.json).
  3. For every game and every category that has a template endpoint, fetches
     the raw template, converts it into our consistent schema, and writes it to:
         assets/gameboost_templates/<category>/<game-slug>.json
     The raw response is also kept under tmp/gameboost/<category>/ for debugging.

  Each category folder under assets/ is WIPED before writing, so the run is a
  clean from-scratch overwrite: new games appear, removed ones disappear, and
  `git diff` shows exactly what changed.

Categories with a template endpoint (the only ones the API exposes):
  accounts    -> /v2/account-offers/templates/{game}    (account_data)
  items       -> /v2/item-offers/templates/{game}       (item_data)
  currencies  -> /v2/currency-offers/templates/{game}   (delivery methods)

Categories present in the data but WITHOUT any template endpoint
(top-ups, boosting, instant-sell, skins) cannot be fetched — the API returns
404 for every offer-type guess. They are reported at the end, not fetched.

Usage (from project root):
    python scripts/fetch_gameboost_templates.py
"""

import json
import os
import re
import shutil
import sys
import time
from collections import Counter

# ── Bootstrap Django ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

import requests  # noqa: E402
from apps.integrations.models import IntegrationAccount, Provider  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
BASE_URL = 'https://api.gameboost.com/v2'
GAMES_URL = f'{BASE_URL}/games?sort=name'
RAW_ROOT = os.path.join(PROJECT_ROOT, 'tmp', 'gameboost')
ASSETS_ROOT = os.path.join(PROJECT_ROOT, 'assets', 'gameboost_templates')
DELAY = 0.3  # seconds between template requests

# Category slug (from games[].services) -> config:
#   endpoint   : URL segment under /v2/
#   folder     : output folder name under assets/ and tmp/
#   data_key   : nested "condition rules" section to convert, if any
CATEGORIES = {
    'accounts': {'endpoint': 'account-offers', 'folder': 'accounts', 'data_key': 'account_data'},
    'items': {'endpoint': 'item-offers', 'folder': 'items', 'data_key': 'item_data'},
    'currencies': {'endpoint': 'currency-offers', 'folder': 'currencies', 'data_key': None},
}


# ── Find a working Gameboost account ────────────────────────────────
def get_api_key():
    accounts = IntegrationAccount.objects.filter(
        provider=Provider.GAMEBOOST,
        is_active=True,
        credential__is_active=True,
    ).select_related('credential')
    for account in accounts:
        key = account.credential.credentials.get('api_key', '')
        if key:
            print(f'Using account: {account.slug} (api_key {key[:8]}...)')
            return key
    raise RuntimeError('No active Gameboost account with an api_key found in the DB')


# ── Schema conversion (shared by accounts / items) ──────────────────
def is_optional_sample(value) -> bool:
    """A sample string beginning with '(optional)' marks an optional field."""
    return isinstance(value, str) and value.startswith('(optional)')


def convert_condition(field_def: dict) -> dict:
    """Convert a Gameboost condition rule into our schema format."""
    condition = field_def.get('condition', 'string')
    values = field_def.get('values')
    schema = {}

    min_match = re.match(r'min:(\d+)', condition)
    max_match = re.match(r'max:(\d+)', condition)

    if condition == 'boolean':
        schema['type'] = 'boolean'
        schema['required'] = False
    elif condition == 'array':
        schema['type'] = 'array'
        schema['required'] = False
    elif condition == 'integer':
        schema['type'] = 'integer'
        schema['required'] = False
        if values:
            schema['values'] = values
    elif min_match:
        schema['type'] = 'integer'
        schema['required'] = False
        schema['min'] = int(min_match.group(1))
    elif max_match:
        schema['type'] = 'number'
        schema['required'] = False
        schema['max'] = int(max_match.group(1))
    elif condition == 'required':
        schema['type'] = 'string'
        schema['required'] = True
        if values:
            schema['values'] = values
    else:
        schema['type'] = 'string'
        schema['required'] = False
        if values:
            schema['values'] = values

    return schema


def build_data_section(raw_section: dict) -> dict:
    """Convert an account_data / item_data section, merging `.*` array items."""
    result = {}
    array_items = {}
    for key, value in raw_section.items():
        if '.*' in key:
            array_items[key.replace('.*', '')] = value
            continue
        result[key] = convert_condition(value)

    for base_key, item_def in array_items.items():
        if base_key in result and result[base_key].get('type') == 'array':
            result[base_key]['items'] = convert_condition(item_def)

    return result


def build_fixed_fields(raw: dict) -> dict:
    """Convert the fixed template fields (title, price, stock, ...) to schema."""
    fields = {}

    string_fields = [
        'title', 'slug', 'login', 'password',
        'email_login', 'email_password',
        'description', 'dump', 'delivery_instructions',
    ]
    for name in string_fields:
        if name not in raw:
            continue
        fields[name] = {
            'type': 'string',
            'required': not is_optional_sample(raw[name]),
        }

    if 'price' in raw:
        fields['price'] = {'type': 'number', 'required': True}

    if 'currency' in raw:
        fields['currency'] = {
            'type': 'string',
            'required': not is_optional_sample(raw['currency']),
        }

    if 'stock' in raw:
        fields['stock'] = {'type': 'integer', 'required': True}

    if 'min_quantity' in raw:
        fields['min_quantity'] = {'type': 'integer', 'required': False}

    if 'is_manual' in raw:
        fields['is_manual'] = {'type': 'boolean', 'required': False, 'default': False}

    if 'delivery_time' in raw:
        fields['delivery_time'] = {
            'type': 'object',
            'required': True,
            'fields': {
                'duration': {'type': 'integer', 'required': True},
                'unit': {
                    'type': 'string',
                    'required': True,
                    'values': ['minutes', 'hours', 'days'],
                },
            },
        }

    if 'image_urls' in raw:
        fields['image_urls'] = {
            'type': 'array',
            'required': False,
            'items': {'type': 'string'},
        }

    return fields


def generate_template(category: str, slug: str, raw: dict) -> dict:
    """Convert one raw API template into our schema format."""
    template_data = raw.get('template', raw)
    cfg = CATEGORIES[category]

    result = {'game': template_data.get('game', slug)}
    result['details'] = build_fixed_fields(template_data)

    # account_data / item_data → game-specific condition fields
    data_key = cfg['data_key']
    if data_key and template_data.get(data_key):
        result[data_key] = build_data_section(template_data[data_key])

    # accounts also carry a game_items catalog → keep as-is
    if template_data.get('game_items'):
        result['game_items'] = template_data['game_items']

    # currencies carry delivery method metadata → keep the rich options as-is
    if category == 'currencies':
        if template_data.get('delivery_method') is not None:
            result['delivery_method'] = template_data['delivery_method']
        if template_data.get('excluded_delivery_fields') is not None:
            result['excluded_delivery_fields'] = template_data['excluded_delivery_fields']
        if template_data.get('delivery_method_options') is not None:
            result['delivery_method_options'] = template_data['delivery_method_options']

    return result


def reset_dir(path: str):
    """Wipe a directory and recreate it empty (from-scratch overwrite)."""
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def main():
    api_key = get_api_key()
    session = requests.Session()
    session.headers.update({'Authorization': f'Bearer {api_key}'})

    # ── Fetch games ────────────────────────────────────────────────
    print('Fetching games...')
    resp = session.get(GAMES_URL, timeout=15)
    resp.raise_for_status()
    games = resp.json()['data']
    print(f'Got {len(games)} games')

    os.makedirs(RAW_ROOT, exist_ok=True)
    with open(os.path.join(RAW_ROOT, 'games.json'), 'w', encoding='utf-8') as f:
        json.dump(games, f, indent=2, ensure_ascii=False)

    # ── Wipe target folders for a clean overwrite ──────────────────
    for cfg in CATEGORIES.values():
        reset_dir(os.path.join(ASSETS_ROOT, cfg['folder']))
        reset_dir(os.path.join(RAW_ROOT, cfg['folder']))

    # ── Build the work list: (category, game_slug) pairs ───────────
    work = []
    skipped_services = Counter()
    for g in games:
        slug = g['slug']
        for service in g.get('services', []):
            if service in CATEGORIES:
                work.append((service, slug))
            else:
                skipped_services[service] += 1

    print(f'{len(work)} template requests across {len(CATEGORIES)} categories\n')

    # ── Fetch + generate ───────────────────────────────────────────
    generated = 0
    failed = []

    for i, (category, slug) in enumerate(work, 1):
        cfg = CATEGORIES[category]
        url = f'{BASE_URL}/{cfg["endpoint"]}/templates/{slug}'
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                failed.append((category, slug, r.status_code))
                print(f'  [{i}/{len(work)}] FAIL ({r.status_code})  {category}/{slug}')
                time.sleep(DELAY)
                continue

            raw = r.json()

            # raw copy for debugging
            raw_path = os.path.join(RAW_ROOT, cfg['folder'], f'{slug}.json')
            with open(raw_path, 'w', encoding='utf-8') as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)

            # transformed template into assets
            template = generate_template(category, slug, raw)
            out_path = os.path.join(ASSETS_ROOT, cfg['folder'], f'{slug}.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(template, f, indent=2, ensure_ascii=False)

            generated += 1
            print(f'  [{i}/{len(work)}] OK    {category}/{slug}')
        except Exception as e:
            failed.append((category, slug, str(e)))
            print(f'  [{i}/{len(work)}] ERROR {category}/{slug} — {e}')

        time.sleep(DELAY)

    # ── Summary ────────────────────────────────────────────────────
    print('\n=== Done ===')
    print(f'Generated: {generated}')
    print(f'Failed:    {len(failed)}')
    for category, slug, reason in failed:
        print(f'  - {category}/{slug}: {reason}')

    if skipped_services:
        print('\n=== Categories with NO template endpoint (cannot be fetched) ===')
        for service, n in skipped_services.most_common():
            print(f'  - {service}: {n} games')
        print('The Gameboost API exposes no template endpoint for these (404).')

    print(f'\nTemplates written under: {ASSETS_ROOT}/<category>/')


if __name__ == '__main__':
    main()
