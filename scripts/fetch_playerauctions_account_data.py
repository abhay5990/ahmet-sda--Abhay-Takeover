"""Fetch PlayerAuctions account server data for all Account games.

For each game that supports "account" product type, fetches:
  /api/games/{gameId}/account/servers → servers.json

Also saves game info from the games list as info.json.

Saves to: tmp/playerauctions/account/{gameId}/

Usage (from project root):
    python scripts/fetch_playerauctions_account_data.py

Note: Requires valid PlayerAuctions session cookies. Update COOKIES dict below
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
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'playerauctions', 'account')
GAMES_PATH = os.path.join(PROJECT_ROOT, '_data_samples', 'playerauctions', 'response', 'games.json')
BASE_URL = 'https://offer-api.playerauctions.com/api/games'
DELAY = 0.3  # seconds between requests

# ── Cookies (update before running) ─────────────────────────────────
COOKIES = {
    'GDPR_cookie': 'true',
    '_ga': 'GA1.1.1177785137.1739104012',
    'fpestid': 'V2nlV_pyoH8VxgH0vIF8yDalDi6ka7oPdwdhbLBB45AtDzk4kDy49XJ4nss7WcItxukvdQ',
    'hl': 'en',
    'display_cookie_popup': 'true',
    'iseu': '%7B%22isEU%22%3Afalse%2C%22ip%22%3A%2278.190.209.27%22%2C%22countryCode%22%3A%22TR%22%2C%22isSC%22%3Afalse%7D',
    'cf_clearance': '8ui.Fs7rNdjblOM_pYtdeXin_Is54HcBh6WWLIN2Uvs-1771456322-1.2.1.1-3eDik2q7LpmW_MrYy6VSz1RSilw1TL8i6Q5YSM3wB9S3rxiRPZliT1nrD8DSxf9pwrzxvkgBTFpKwP78pHXHjFkh6irFr3zxxxAs0DzpyHRlF9UBBN7FWC_oE1nKiVr_EGH_eIMj8_KFZXL8OxfgvjEwH63g9_zfyt0peGfSepZg2z3lhHf3lAw28hdA1aewrqQ3GjaRz91H0xhd3pfTqYpj1azaWZPjw0rME5vPSa4',
    '_cfuvid': 'dzVP268B3bOXxrh7BLkMzdt36arv_47au4G34RFfxOY-1774653333.3134167-1.0.1.1-R2HoDV2BnazXC3FCui89_0G0Tz9I4JArFLh5M4ILonk',
    'Production_logged_in': '2517509',
    'memberId': '2517509',
    '_gcl_au': '1.1.1096676164.1774599235.1872287290.1774968001.1774968442',
    'Production_access_token': 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyNTE3NTA5Iiwic2lkIjoiNjljYmUwMGFmNDIxODcwNzQ5NGE2ZGQxIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50LnBhLmNvbSIsImFjYyI6IlNlbmVyIiwiY2xpZW50X2lkIjoicGEiLCJzY29wZSI6InBhIiwic3RhdHVzIjoiMSIsIm5iZiI6MTc3NDk2ODg0MiwiZXhwIjoxNzc0OTcwNjQyLCJhdWQiOiJodHRwczovL2FjY291bnQucGEuY29tIn0.kPgX6V6z6DdaI4wbPS19M20rR6nW5gOcxdRpZmd2TpZS4nYY0IkPRHlYjGX3QBWhjktlT18zk8ycPijWdxS8UpjtEArz_Y9hBUM0qDIpDzGNwoAIgUFjXICm6-Kh7hLNcBZ0D_YGNNrDW8lXfHwqPJihBG-djBP0NL6sbpr0AIIwt_cYX2FZ3Z1CLG4c6GhJlhXcWDx-cDQNfrKbMk8-oOSymWhbYObbvk9jF2khzGSOYBwbePuskKPP0R1r-CqSGPUgZeWgS5eC_VKNA5ECNfWH52BZuuMAdpLgvqqa15arYj8mbPXPT_RGL6J_MPQSmObXBm8cUKeH1BBuB-iCwSsYDQbbBsIqxZN1o2l4tpLAIHOpC9A7R764hP7TNL1i06F4g3D9yJ0PJMAUBMWqjq7TTGIYkh1aptcn9EXWShSsc9SvHo9O8YiGoF_B1lIKXKF6XZWgm-4ErabV32_UbFESGsf7NVdw2Ax7ruouW0x8oqKwUJbHGg7Ias7q9PL6TOq62X55YDqSlSqFdDu6l8MfE0dAfsvOeZ024HABA7cjiHrplCeGIA1P-DvS2gPibm7OFfXBSsEkT0z0ov6QbPoXLVgI4CCLuuXp2M40UGrXmeHoEjRCaAOxF_pYUflUkhgWYacbv7JYVFHt7KDcirZRRpPcCxwz_q5bJs_lYDI',
    'Production_refresh_token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJuYW1laWQiOiIyNTE3NTA5Iiwic2lkIjoiNjljYmMzNDc0MTc1NjAwNzQ5Y2NmZjNjIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50LnBhLmNvbSIsImFjYyI6IlNlbmVyIiwiY2xpZW50X2lkIjoicGEiLCJzY29wZSI6InBhIiwic3RhdHVzIjoiMSIsIm5iZiI6MTc3NDk2ODg0MiwiZXhwIjoxNzc1MDQ3ODc5LCJhdWQiOlsiaHR0cHM6Ly9hY2NvdW50LnBhLmNvbSIsImh0dHBzOi8vYWNjb3VudC5wYS5jb20iLCJodHRwczovL2FjY291bnQucGEuY29tIiwiaHR0cHM6Ly9hY2NvdW50LnBhLmNvbSIsImh0dHBzOi8vYWNjb3VudC5wYS5jb20iLCJodHRwczovL2FjY291bnQucGEuY29tIl0sImlhdCI6MTc3NDk2ODg0Mn0.oXdTfW0dyItRRAZVDZxLYCRysOJgdNGKxj2QLL4h1Bw',
    '__cf_bm': 'hS36FxuysMyrajF_E8QvCVcc7SywdPKohjIv.T_a7BY-1774969621.1622298-1.0.1.1-rjf3q8UZN.4gYTB_sFXTENdsFlhqZc3doJrCU8n_aDY4toOBDqbmHSg0mmGvunY5hgfLAgVKC2yMtgOYeDOTsw1qXLwt98MisiqfYC3FTy82X81a1jK3_ds3H7YGiFJg',
    '_ga_V0RV18SNGD': 'GS2.1.s1774967887$o307$g1$t1774969965$j53$l1$h506186259',
}

HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US',
    'cache-control': 'no-cache',
    'origin': 'https://member.playerauctions.com',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
}


def load_account_games():
    """Load games that support 'account' product type from games.json."""
    with open(GAMES_PATH, encoding='utf-8') as f:
        data = json.load(f)
    games = data.get('data', data) if isinstance(data, dict) else data
    return [g for g in games if 'account' in g.get('productType', '')]


def fetch_and_save(url, out_path):
    """Fetch URL and save JSON response. Returns status string."""
    if os.path.exists(out_path):
        return 'skip'
    try:
        resp = requests.get(url, cookies=COOKIES, headers=HEADERS, timeout=15)
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
    # Validate cookies
    if not COOKIES.get('Production_access_token'):
        print('ERROR: Cookies are empty! Update COOKIES dict with fresh browser values.')
        print('Required: Production_access_token, Production_refresh_token, cf_clearance, __cf_bm')
        sys.exit(1)

    if not os.path.exists(GAMES_PATH):
        print(f'ERROR: Games list not found: {GAMES_PATH}')
        sys.exit(1)

    games = load_account_games()
    print(f'Found {len(games)} games with account product type')

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stats = {'ok': 0, 'skip': 0, 'fail': 0}
    failures = []

    for i, game in enumerate(games, 1):
        game_id = game['gameId']
        game_name = game['gameName']
        game_dir = os.path.join(OUTPUT_DIR, str(game_id))
        os.makedirs(game_dir, exist_ok=True)

        # Save game info
        info_path = os.path.join(game_dir, 'info.json')
        if not os.path.exists(info_path):
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(game, f, indent=2, ensure_ascii=False)

        # Fetch servers
        servers_path = os.path.join(game_dir, 'servers.json')
        servers_url = f'{BASE_URL}/{game_id}/account/servers'
        result = fetch_and_save(servers_url, servers_path)

        label = f'[{i:>3}/{len(games)}] {game_id:>5} {game_name}'
        if result == 'skip':
            stats['skip'] += 1
        elif result == 'ok':
            stats['ok'] += 1
            print(f'  {label} — {result}')
        else:
            stats['fail'] += 1
            failures.append((game_id, game_name, result))
            print(f'  {label} — FAIL {result}')

        # Rate limit
        if result != 'skip':
            time.sleep(DELAY)

    # ── Summary ─────────────────────────────────────────────────────
    print(f'\n=== Done ===')
    print(f'Success: {stats["ok"]}')
    print(f'Skipped (already exists): {stats["skip"]}')
    print(f'Failed: {stats["fail"]}')
    if failures:
        for gid, name, result in failures:
            print(f'  - {gid} ({name}): {result}')
    print(f'\nData saved to: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
