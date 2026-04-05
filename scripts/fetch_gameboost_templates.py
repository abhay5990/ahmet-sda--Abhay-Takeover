"""Fetch Gameboost account-offer templates for all account games.

Reads the API key from the DB (gameboost-store4gamers),
hits /v2/account-offers/templates/{slug} for each game,
and saves the raw results to tmp/gameboost/accounts/{slug}.json.

Usage (from project root):
    python scripts/fetch_gameboost_templates.py
"""

import json
import os
import sys
import time

# ── Bootstrap Django ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

import requests  # noqa: E402
from apps.integrations.models import IntegrationAccount  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'gameboost', 'accounts')
BASE_URL = 'https://api.gameboost.com/v2/account-offers/templates'
DELAY = 0.3  # seconds between requests (be nice to API)

# ── Read API key from DB ────────────────────────────────────────────
account = IntegrationAccount.objects.get(slug='gameboost-store4gamers')
creds = account.credential.credentials
api_key = creds.get('api_key', '')
if not api_key:
    raise RuntimeError('No api_key found for gameboost-store4gamers')

print(f'API key loaded: {api_key[:8]}...')

# ── Load game slugs ────────────────────────────────────────────────
services_path = os.path.join(PROJECT_ROOT, '_data_samples', 'gameboost', 'services.json')
with open(services_path) as f:
    data = json.load(f)

games = data['props']['games']
account_slugs = []
for g in games:
    cats = [c.get('slug', '') for c in g.get('categories', g.get('services', []))]
    if 'accounts' in cats:
        account_slugs.append(g['slug'])

print(f'Found {len(account_slugs)} account games')

# ── Fetch templates ─────────────────────────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)

headers = {'Authorization': f'Bearer {api_key}'}
success = 0
failed = []
skipped = 0

for i, slug in enumerate(account_slugs, 1):
    out_path = os.path.join(OUTPUT_DIR, f'{slug}.json')

    # Skip if already fetched
    if os.path.exists(out_path):
        skipped += 1
        continue

    try:
        resp = requests.get(f'{BASE_URL}/{slug}', headers=headers, timeout=15)
        if resp.status_code == 200:
            template_data = resp.json()
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=2, ensure_ascii=False)
            success += 1
            print(f'  [{i}/{len(account_slugs)}] OK: {slug}')
        else:
            failed.append((slug, resp.status_code))
            print(f'  [{i}/{len(account_slugs)}] FAIL ({resp.status_code}): {slug}')
    except Exception as e:
        failed.append((slug, str(e)))
        print(f'  [{i}/{len(account_slugs)}] ERROR: {slug} — {e}')

    time.sleep(DELAY)

# ── Summary ─────────────────────────────────────────────────────────
print(f'\n=== Done ===')
print(f'Success: {success}')
print(f'Skipped (already exists): {skipped}')
print(f'Failed: {len(failed)}')
if failed:
    for slug, reason in failed:
        print(f'  - {slug}: {reason}')
print(f'\nTemplates saved to: {OUTPUT_DIR}')
