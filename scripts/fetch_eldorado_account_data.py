"""Fetch Eldorado account offer data for all Account games.

For each Account game, fetches:
  1. /api/library/{gameId}/Account           -> service.json  (trade environments + attributes)
  2. /api/library/{gameId}/Account/attributes/offers -> attributes_offers.json

Saves to: tmp/eldorado/account/{gameId}/

Uses Django integration account (eldorado-store4gamers) for auth.
Existing files are skipped unless --force is passed.

Usage (from project root):
    python scripts/fetch_eldorado_account_data.py
    python scripts/fetch_eldorado_account_data.py --account eldorado-store4gamers
    python scripts/fetch_eldorado_account_data.py --force          # re-fetch all
    python scripts/fetch_eldorado_account_data.py --game-id 32     # single game
"""

import argparse
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

from apps.integrations.models import IntegrationAccount  # noqa: E402
from apps.integrations.providers.registry import get_or_build_client  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'eldorado', 'account')
SERVICES_PATH = os.path.join(PROJECT_ROOT, '_data_samples', 'eldorado', 'services.json')
BASE_URL = 'https://www.eldorado.gg/api/library'
DELAY = 0.3  # seconds between requests


def load_account_games():
    """Load Account category games from services.json."""
    with open(SERVICES_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return [g for g in data if g.get('category') == 'Account']


def find_account(slug=None):
    """Find an active Eldorado integration account."""
    if slug:
        try:
            return IntegrationAccount.objects.select_related('credential').get(
                slug=slug, is_active=True,
            )
        except IntegrationAccount.DoesNotExist:
            print(f"ERROR: Account '{slug}' not found or inactive")
            return None

    accounts = IntegrationAccount.objects.select_related('credential').filter(
        provider='eldorado', is_active=True,
    )
    if not accounts.exists():
        print("ERROR: No active Eldorado accounts found in DB")
        return None

    account = accounts.first()
    print(f"Using account: {account.slug}")
    return account


def fetch_url(facade, url, params=None):
    """Fetch a URL using the facade's transport and auth headers.

    Returns (json_data, status_code) or (None, error_string).
    """
    transport = facade._exec._transport
    auth_headers = facade._exec.get_auth_headers()

    headers = {
        **auth_headers,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US',
    }

    try:
        from apis_sdk.core.enums import HttpMethod
        response = transport.request(
            HttpMethod.GET,
            url,
            headers=headers,
            params=params,
            timeout=15,
        )
        if response.is_success:
            return response.json(), response.status_code
        return None, f'http_{response.status_code}'
    except Exception as e:
        return None, f'error: {e}'


def fetch_and_save(facade, url, out_path, *, force=False, params=None):
    """Fetch URL via SDK transport and save JSON response."""
    if not force and os.path.exists(out_path):
        return 'skip'

    data, status = fetch_url(facade, url, params=params)
    if data is not None:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return 'ok'
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--account', type=str, default=None,
                        help='Account slug (default: auto-detect first active eldorado account)')
    parser.add_argument('--force', action='store_true',
                        help='Re-fetch even if files already exist')
    parser.add_argument('--game-id', type=str, default=None,
                        help='Fetch single game ID only (e.g. "32" for Valorant)')
    args = parser.parse_args()

    # ── 1. Build SDK client ────────────────────────────────────────
    account = find_account(args.account)
    if not account:
        sys.exit(1)
    if not hasattr(account, 'credential') or not account.credential.is_active:
        sys.exit(f'ERROR: {account.slug} has no active credentials')

    facade = get_or_build_client('eldorado', account.credential)
    print(f"SDK client ready ({account.slug})")

    # ── 2. Load game list ──────────────────────────────────────────
    games = load_account_games()
    print(f'Found {len(games)} Account games')

    if args.game_id:
        games = [g for g in games if str(g['gameId']) == args.game_id]
        if not games:
            print(f'ERROR: Game ID {args.game_id} not found in services.json')
            sys.exit(1)
        print(f'Filtering to game ID: {args.game_id}')

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 3. Fetch ───────────────────────────────────────────────────
    stats = {'ok': 0, 'skip': 0, 'fail': 0}
    failures = []

    for i, game in enumerate(games, 1):
        game_id = game['gameId']
        game_name = game['gameName']
        game_dir = os.path.join(OUTPUT_DIR, game_id)
        os.makedirs(game_dir, exist_ok=True)

        # Save basic game info
        info_path = os.path.join(game_dir, 'info.json')
        if not os.path.exists(info_path) or args.force:
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(game, f, indent=2, ensure_ascii=False)

        # 1. Service details (trade environments + attributes)
        svc_path = os.path.join(game_dir, 'service.json')
        svc_url = f'{BASE_URL}/{game_id}/Account'
        r1 = fetch_and_save(facade, svc_url, svc_path,
                            force=args.force, params={'locale': 'en-US'})

        # 2. Offer attributes
        attr_path = os.path.join(game_dir, 'attributes_offers.json')
        attr_url = f'{BASE_URL}/{game_id}/Account/attributes/offers'
        r2 = fetch_and_save(facade, attr_url, attr_path,
                            force=args.force, params={'locale': 'en-US'})

        # Stats
        label = f'[{i:>3}/{len(games)}] {game_id:>4} {game_name}'
        if r1 == 'skip' and r2 == 'skip':
            stats['skip'] += 1
        elif r1 == 'ok' or r2 == 'ok':
            stats['ok'] += 1
            print(f'  {label} -- service:{r1} attr:{r2}')
        else:
            stats['fail'] += 1
            failures.append((game_id, game_name, r1, r2))
            print(f'  {label} -- FAIL service:{r1} attr:{r2}')

        # Rate limit
        if r1 != 'skip' or r2 != 'skip':
            time.sleep(DELAY)

    # ── Summary ─────────────────────────────────────────────────────
    print(f'\n=== Done ===')
    print(f'Success: {stats["ok"]}')
    print(f'Skipped (already exists): {stats["skip"]}')
    print(f'Failed: {stats["fail"]}')
    if failures:
        for gid, name, r1, r2 in failures:
            print(f'  - {gid} ({name}): service={r1}, attr={r2}')
    print(f'\nData saved to: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
