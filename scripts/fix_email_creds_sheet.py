"""Fix email:email_password column in Google Sheets.

Reads from lzt_kapunkap_sorted JSON files and updates ONLY the
email:email_password column — all other columns are untouched.

Credential processing rules:
  - Rambler:          email:email_password:secret_answer
  - Outlook long      (>=200 chars, has ':'): keep only before first ':'
  - Outlook 2-colon   (<200 chars, 2 ':'s): email_pass:security_email:security_email_pass
  - Others:           email:email_password

Usage:
    python scripts/fix_email_creds_sheet.py

Add more games to GAMES dict as needed.
"""

from __future__ import annotations

import json
import os
import re

import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────────────────

SA_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'tmp', 'sa_temp.json')

DATA_BASE = os.path.join(os.path.dirname(__file__), '..', 'tmp', 'lzt_kapunkap_sorted')

# game_folder → spreadsheet_id
GAMES: dict[str, str] = {
    'fortnite': '1qx6FuYC275EgGm2Yxi7TodoGSeSsUxENkEAMtPGRaiY',
    'uplay':    '1FZoOzFNx1BqMBPl9j2JugML8uR1NIdhPFUaADOE_KEw',
    # Diğer oyunları buraya ekle:
    # 'ea':        '<ea_spreadsheet_id>',
    # 'riot':      '<riot_spreadsheet_id>',
    # 'supercell': '<supercell_spreadsheet_id>',
    # 'mihoyo':    '<mihoyo_spreadsheet_id>',
    # 'minecraft': '<minecraft_spreadsheet_id>',
}

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# ── Credential processing ─────────────────────────────────────────────────

def _build_email_cred(item: dict) -> str:
    """Build the corrected email:email_password string for a JSON item."""
    ed = item.get('emailLoginData') or {}
    email = (ed.get('login') or '').strip()
    email_password = (ed.get('password') or '').strip()
    secret_answer = (ed.get('newSecretAnswer') or '').strip()
    ep = (item.get('email_provider') or '').lower()

    if not email or not email_password:
        return ''

    security_email = ''
    security_email_password = ''

    if len(email_password) >= 200 and ':' in email_password:
        # Outlook long format: keep only before first ':'
        email_password = email_password.split(':', 1)[0]
    elif email_password.count(':') == 2 and len(email_password) < 200:
        # Outlook security format: pass:security_email:security_email_pass
        parts = email_password.split(':', 2)
        email_password = parts[0]
        security_email = parts[1] if len(parts) > 1 else ''
        security_email_password = parts[2] if len(parts) > 2 else ''

    parts = [email, email_password]
    if 'rambler' in ep and secret_answer:
        parts.append(secret_answer)
    elif security_email:
        parts.append(security_email)
        if security_email_password:
            parts.append(security_email_password)

    return ':'.join(parts)


# ── Sheet helpers ─────────────────────────────────────────────────────────

def _login_from_cell(cell: str) -> str:
    """Extract login (part before first ':') from a login:password cell."""
    if ':' in cell:
        return cell.split(':', 1)[0].strip()
    return cell.strip()


def _col_letter(index: int) -> str:
    """Convert 0-based column index to A1 letter (e.g. 0→A, 2→C)."""
    result = ''
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


# ── Core logic ────────────────────────────────────────────────────────────

def fix_game(gc: gspread.Client, game: str, spreadsheet_id: str) -> None:
    game_dir = os.path.join(DATA_BASE, game)
    if not os.path.isdir(game_dir):
        print(f'[{game}] Klasör bulunamadı: {game_dir}')
        return

    spreadsheet = gc.open_by_key(spreadsheet_id)
    available_tabs = {ws.title: ws for ws in spreadsheet.worksheets()}
    json_files = {
        os.path.splitext(f)[0]: os.path.join(game_dir, f)
        for f in sorted(os.listdir(game_dir))
        if f.endswith('.json')
    }

    print(f'\n=== {game.upper()} ===')
    print(f'  JSON dosyaları: {sorted(json_files.keys())}')
    print(f'  Sheet tabları:  {sorted(available_tabs.keys())}')

    for month, json_path in sorted(json_files.items()):
        if month not in available_tabs:
            print(f'  [{month}] Tab yok, atlanıyor.')
            continue

        ws = available_tabs[month]

        # Load JSON data: build login → email_cred mapping
        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)

        login_to_email_cred: dict[str, str] = {}
        for item in data:
            ld = item.get('loginData') or {}
            login = (ld.get('login') or '').strip()
            if login:
                login_to_email_cred[login] = _build_email_cred(item)

        # Read sheet headers
        all_values = ws.get_all_values()
        if not all_values:
            print(f'  [{month}] Sheet boş, atlanıyor.')
            continue

        headers = all_values[0]
        try:
            email_col_idx = next(
                i for i, h in enumerate(headers)
                if h.strip().lower() in ('email:email_password', 'email:emailpassword', 'email:email_pass')
            )
        except StopIteration:
            print(f'  [{month}] "email:email_password" kolonu bulunamadı. Mevcut başlıklar: {headers}')
            continue

        try:
            login_col_idx = next(
                i for i, h in enumerate(headers)
                if h.strip().lower() in ('login:password', 'login:pass', 'login')
            )
        except StopIteration:
            print(f'  [{month}] "login:password" kolonu bulunamadı.')
            continue

        # Build corrected column values (skip header row)
        data_rows = all_values[1:]
        if not data_rows:
            print(f'  [{month}] Veri yok.')
            continue

        updates: list[list[str]] = []
        matched = 0
        not_found = 0

        for row in data_rows:
            login_cell = row[login_col_idx] if len(row) > login_col_idx else ''
            login = _login_from_cell(login_cell)
            corrected = login_to_email_cred.get(login, '')
            if corrected:
                matched += 1
            else:
                not_found += 1
            updates.append([corrected])

        # Write only the email:email_password column
        col_letter = _col_letter(email_col_idx)
        start_row = 2  # row 1 is header
        end_row = start_row + len(updates) - 1
        range_notation = f'{col_letter}{start_row}:{col_letter}{end_row}'

        ws.update(values=updates, range_name=range_notation, value_input_option='RAW')
        print(f'  [{month}] Güncellendi — {matched} eşleşti, {not_found} bulunamadı.')


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    sa_path = os.path.abspath(SA_JSON_PATH)
    if not os.path.exists(sa_path):
        print(f'Service account JSON bulunamadı: {sa_path}')
        return

    with open(sa_path) as f:
        sa_info = json.load(f)

    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    print(f'Authenticated as: {sa_info.get("client_email", "")}')

    for game, spreadsheet_id in GAMES.items():
        fix_game(gc, game, spreadsheet_id)

    print('\nTamamlandı.')


if __name__ == '__main__':
    main()
