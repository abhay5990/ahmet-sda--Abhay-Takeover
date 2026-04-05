"""Fetch Eldorado account offer data for all Account games.

For each Account game, fetches:
  1. /api/library/{gameId}/Account           → service.json  (trade environments + attributes)
  2. /api/library/{gameId}/Account/attributes/offers → attributes_offers.json

Saves to: tmp/eldorado/account/{gameId}/

Usage (from project root):
    python scripts/fetch_eldorado_account_data.py

Note: Requires valid Eldorado session cookies. Update COOKIES dict below
      with fresh values from browser DevTools before running.
"""

import json
import os
import sys
import time

import requests

# ── Config ──────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'eldorado', 'account')
SERVICES_PATH = os.path.join(PROJECT_ROOT, '_data_samples', 'eldorado', 'services.json')
BASE_URL = 'https://www.eldorado.gg/api/library'
DELAY = 0.3  # seconds between requests

# ── Cookies (update before running) ─────────────────────────────────
# Minimum required cookies — copy fresh values from browser DevTools
COOKIES = {
    '__Host-EldoradoIdToken': 'eyJraWQiOiJETTJSdklPTldaZThEd01ZNDNlbHZDTE9mbmZVNFozcWljOFQ4bmhTbmFBPSIsImFsZyI6IlJTMjU2In0.eyJhdF9oYXNoIjoicVp6Y2JHUHROd0hzUmtVcTFmN2FDdyIsInN1YiI6ImRhYTZhNmJhLWMzZGMtNDQ0OC05YTQ0LTU3ODE0NmYxYTBlMSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJpc3MiOiJodHRwczpcL1wvY29nbml0by1pZHAudXMtZWFzdC0yLmFtYXpvbmF3cy5jb21cL3VzLWVhc3QtMl9NbG56Q0ZnSGsiLCJjb2duaXRvOnVzZXJuYW1lIjoiZGFhNmE2YmEtYzNkYy00NDQ4LTlhNDQtNTc4MTQ2ZjFhMGUxIiwiY3VzdG9tOnVzZXJpZF9vdmVycmlkZSI6ImF1dGgwfDYwYzU2YWQ4MTU1ODlkMDA2OTM0OGI0YiIsInVzZXJJZCI6ImF1dGgwfDYwYzU2YWQ4MTU1ODlkMDA2OTM0OGI0YiIsIm9yaWdpbl9qdGkiOiJkNGVmYzk0Yi04OTBkLTQxNTAtYjFmYS03ZWJkNTRkZGNlNzgiLCJhdWQiOiIzYTRoYWw2amdsOGdmNWhubmpvMDZrMDVzNSIsImlkZW50aXRpZXMiOlt7InVzZXJJZCI6IjEwNTgwMjgzMTU2NjI1MzMxNTAxOSIsInByb3ZpZGVyTmFtZSI6Ikdvb2dsZSIsInByb3ZpZGVyVHlwZSI6Ikdvb2dsZSIsImlzc3VlciI6bnVsbCwicHJpbWFyeSI6ImZhbHNlIiwiZGF0ZUNyZWF0ZWQiOiIxNjQxMDc3ODYzODM5In1dLCJldmVudF9pZCI6ImFiOWE4ZmQ2LTQ5YzMtNGY3Zi1hYzAxLTU2YTljMmE4MGI5YiIsInRva2VuX3VzZSI6ImlkIiwiYXV0aF90aW1lIjoxNzc0MTgyNzI4LCJleHAiOjE3NzQ5NTY1NDEsImlhdCI6MTc3NDk1NDc0MSwianRpIjoiOTE1YzdlOWItOTFlZC00YTk3LWE1MmEtNTc0N2Y1NzVlYTRiIiwiZW1haWwiOiJzZW5lcmFkMTVAZ21haWwuY29tIn0.e_W8f0MaWPqP6GCuKnZTzbfFXDKxjdn59DtwnC1yCGkxAcn7Qd81UT_Zx-UIcbQkPKuGCrkOI_1WCFxKld80h-OuHDb-goeIMh-XI_5i-eAAvGo4fUXt8qXGSf3TtYQjGppedbFednfKtRBKnLeRBIUKUJN4en0FuasTedg5NWplLwiPt2IiIdHhEFThVO9QWGlWRBY86Ok5WcU2GxxW8reQm4Xo0PD4Ds4H4dA0ag17usJc4YJ3DwoRlgCp4JfKV9GAilU6xvOsQgpwCZCNxJE3kY86F8wczJP0RKQCR0IZxXgdUPCwPDpYjCSI057C0JfBTGyv4SeUDAI95RtKjg',   # ← paste from browser
    '__Host-XSRF-TOKEN': 'ca7df5344df7e8f4100b61dfa971085cab26a9dd770f2b25ddfcc391de7231ec',        # ← paste from browser
    'cf_clearance': 'R6d8P1ng2aywZzgtKC_gjmUi.lzC_UX4vM4Cj_nSRWw-1774182676-1.2.1.1-SRw2tsK_jCbO0ylxNvZ6qAySn4p_IKICZyFIRUTFiW9oaAKETpg23Y0maHe96UzEU__G4LjmwthGKf49kpqirjKFkj2yOQTgq8uJJCd_rXHHXRvGODE8Zg8DiCu7s90eyygE0Mgvftl1SNg95BmNRcVsz8Y0kzUIfYIwr6t7gp7x_yNn_k2mmEXALzEjYjxNlmVxIs7rlL5lvSoRMl.s0avZtgkRogiwlHkbXBToHNQ',             # ← paste from browser
    'eldoradogg_locale': 'en-US',
}

HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US',
    'cache-control': 'no-cache',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
    'x-xsrf-token': '',  # ← will be set from COOKIES
}


def load_account_games():
    """Load Account category games from services.json."""
    with open(SERVICES_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return [g for g in data if g.get('category') == 'Account']


def fetch_and_save(url, out_path, params=None):
    """Fetch URL and save JSON response. Returns True on success."""
    if os.path.exists(out_path):
        return 'skip'
    try:
        resp = requests.get(url, params=params, cookies=COOKIES, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return 'ok'
        else:
            return f'http_{resp.status_code}'
    except Exception as e:
        return f'error: {e}'


def main():
    # Set XSRF header from cookie
    HEADERS['x-xsrf-token'] = COOKIES.get('__Host-XSRF-TOKEN', '')

    # Validate cookies
    if not COOKIES.get('__Host-EldoradoIdToken'):
        print('ERROR: Cookies are empty! Update COOKIES dict with fresh browser values.')
        print('Required: __Host-EldoradoIdToken, __Host-XSRF-TOKEN, cf_clearance')
        sys.exit(1)

    games = load_account_games()
    print(f'Found {len(games)} Account games')

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stats = {'ok': 0, 'skip': 0, 'fail': 0}
    failures = []

    for i, game in enumerate(games, 1):
        game_id = game['gameId']
        game_name = game['gameName']
        game_dir = os.path.join(OUTPUT_DIR, game_id)
        os.makedirs(game_dir, exist_ok=True)

        # Also save basic game info from library
        info_path = os.path.join(game_dir, 'info.json')
        if not os.path.exists(info_path):
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(game, f, indent=2, ensure_ascii=False)

        # 1. Service details (trade environments + attributes)
        svc_path = os.path.join(game_dir, 'service.json')
        svc_url = f'{BASE_URL}/{game_id}/Account'
        r1 = fetch_and_save(svc_url, svc_path, params={'locale': 'en-US'})

        # 2. Offer attributes
        attr_path = os.path.join(game_dir, 'attributes_offers.json')
        attr_url = f'{BASE_URL}/{game_id}/Account/attributes/offers'
        r2 = fetch_and_save(attr_url, attr_path, params={'locale': 'en-US'})

        # Stats
        label = f'[{i:>3}/{len(games)}] {game_id:>4} {game_name}'
        if r1 == 'skip' and r2 == 'skip':
            stats['skip'] += 1
        elif r1 == 'ok' or r2 == 'ok':
            stats['ok'] += 1
            print(f'  {label} — service:{r1} attr:{r2}')
        else:
            stats['fail'] += 1
            failures.append((game_id, game_name, r1, r2))
            print(f'  {label} — FAIL service:{r1} attr:{r2}')

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
