"""Fix uplay Google Sheet — rewrite incorrect tabs and create missing ones.

Reads from lzt_kapunkap_sorted/uplay JSON files, excludes accounts
found in combo.txt through combo6.txt (including combo5_valid.txt),
and writes corrected data to the Google Sheet.

Actions:
  - 2025-04: Clear and rewrite (had cross-game contamination)
  - 2025-08: Add 1 missing record
  - 2025-09: Clear and rewrite (combo exclusions were incomplete)
  - 2026-01 ~ 2026-05: Create new tabs and write data

Usage:
    python scripts/fix_uplay_sheet.py [--dry-run]
"""

from __future__ import annotations

import json
import os
import sys
import time

import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────────────────

BASE_DIR = os.path.join(os.path.dirname(__file__), '..')
SA_JSON_PATH = os.path.join(BASE_DIR, 'tmp', 'sa_temp.json')
DATA_BASE = os.path.join(BASE_DIR, 'tmp', 'lzt_kapunkap_sorted', 'uplay')
SPREADSHEET_ID = '1FZoOzFNx1BqMBPl9j2JugML8uR1NIdhPFUaADOE_KEw'

COMBO_FILES = [
    'combo.txt', 'combo2.txt', 'combo3.txt', 'combo4.txt',
    'combo5.txt', 'combo5_valid.txt', 'combo6.txt',
]

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

HEADERS = ['title', 'login:password', 'email:email_password', 'price_usd', 'purchased_at']


# ── Helpers ───────────────────────────────────────────────────────────────

def load_excluded_logins() -> set[str]:
    excluded = set()
    for fname in COMBO_FILES:
        path = os.path.join(BASE_DIR, 'tmp', fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if ':' in line:
                    login = line.split(':', 1)[0].strip()
                    if login:
                        excluded.add(login)
    return excluded


def build_email_cred(item: dict) -> str:
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
        email_password = email_password.split(':', 1)[0]
    elif email_password.count(':') == 2 and len(email_password) < 200:
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


def build_rows(json_path: str, excluded: set[str]) -> list[list[str]]:
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    rows = []
    for item in data:
        ld = item.get('loginData') or {}
        login = (ld.get('login') or '').strip()
        password = (ld.get('password') or '').strip()

        if not login:
            continue
        if login in excluded:
            continue

        title = item.get('title', '')
        login_pass = f'{login}:{password}' if password else login
        email_cred = build_email_cred(item)
        price = str(item.get('price', '')).replace('.', ',') if item.get('price') is not None else ''
        purchased = item.get('purchased_at', '')

        rows.append([title, login_pass, email_cred, price, purchased])

    return rows


def col_letter(index: int) -> str:
    result = ''
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


# ── Actions ───────────────────────────────────────────────────────────────

def rewrite_tab(spreadsheet, tab_name: str, rows: list[list[str]], dry_run: bool) -> None:
    """Clear a tab and write fresh data (header + rows)."""
    tabs = {ws.title: ws for ws in spreadsheet.worksheets()}

    if tab_name in tabs:
        ws = tabs[tab_name]
        if dry_run:
            print(f'  [DRY-RUN] Would clear tab "{tab_name}" and write {len(rows)} rows')
            return
        ws.clear()
        time.sleep(1)
    else:
        if dry_run:
            print(f'  [DRY-RUN] Would create tab "{tab_name}" and write {len(rows)} rows')
            return
        ws = spreadsheet.add_worksheet(title=tab_name, rows=len(rows) + 1, cols=len(HEADERS))
        time.sleep(1)

    all_data = [HEADERS] + rows
    ws.update(values=all_data, range_name='A1', value_input_option='RAW')
    print(f'  [{tab_name}] Yazıldı — {len(rows)} satır')


def patch_missing_rows(spreadsheet, tab_name: str, expected_rows: list[list[str]], dry_run: bool) -> None:
    """Find missing rows in existing tab and append them."""
    tabs = {ws.title: ws for ws in spreadsheet.worksheets()}
    if tab_name not in tabs:
        print(f'  [{tab_name}] Tab bulunamadı!')
        return

    ws = tabs[tab_name]
    all_values = ws.get_all_values()
    data_rows = all_values[1:] if all_values else []

    # Existing logins in sheet
    existing_logins = set()
    for r in data_rows:
        if len(r) > 1 and ':' in r[1]:
            existing_logins.add(r[1].split(':', 1)[0].strip())
        elif len(r) > 1:
            existing_logins.add(r[1].strip())

    # Find missing rows
    missing = []
    for row in expected_rows:
        login = row[1].split(':', 1)[0].strip() if ':' in row[1] else row[1].strip()
        if login not in existing_logins:
            missing.append(row)

    if not missing:
        print(f'  [{tab_name}] Eksik kayıt yok, zaten doğru.')
        return

    if dry_run:
        print(f'  [DRY-RUN] Would append {len(missing)} missing rows to "{tab_name}"')
        for r in missing[:3]:
            print(f'    {r[1][:50]}...')
        return

    # Resize sheet if needed, then append missing rows
    needed_rows = len(all_values) + len(missing)
    if ws.row_count < needed_rows:
        ws.resize(rows=needed_rows)
        time.sleep(1)

    start_row = len(all_values) + 1
    end_row = start_row + len(missing) - 1
    range_notation = f'A{start_row}:E{end_row}'
    ws.update(values=missing, range_name=range_notation, value_input_option='RAW')
    print(f'  [{tab_name}] {len(missing)} eksik satır eklendi')


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print('=== DRY-RUN MODE — hiçbir şey yazılmayacak ===\n')

    sa_path = os.path.abspath(SA_JSON_PATH)
    if not os.path.exists(sa_path):
        print(f'Service account JSON bulunamadı: {sa_path}')
        return

    with open(sa_path) as f:
        sa_info = json.load(f)

    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)

    excluded = load_excluded_logins()
    print(f'Hariç tutulan login sayısı: {len(excluded)}')

    # ── Step 1: Rewrite 2025-04 (cross-game contamination) ───────────────
    print('\n── 2025-04: Temizle ve yeniden yaz ──')
    rows_04 = build_rows(os.path.join(DATA_BASE, '2025-04.json'), excluded)
    print(f'  Beklenen satır: {len(rows_04)}')
    rewrite_tab(spreadsheet, '2025-04', rows_04, dry_run)
    if not dry_run:
        time.sleep(2)

    # ── Step 2: Patch 2025-08 (1 missing record) ─────────────────────────
    print('\n── 2025-08: Eksik kayıtları ekle ──')
    rows_08 = build_rows(os.path.join(DATA_BASE, '2025-08.json'), excluded)
    print(f'  Beklenen satır: {len(rows_08)}')
    patch_missing_rows(spreadsheet, '2025-08', rows_08, dry_run)
    if not dry_run:
        time.sleep(2)

    # ── Step 3: Rewrite 2025-09 (incomplete combo exclusion) ─────────────
    print('\n── 2025-09: Temizle ve yeniden yaz ──')
    rows_09 = build_rows(os.path.join(DATA_BASE, '2025-09.json'), excluded)
    print(f'  Beklenen satır: {len(rows_09)}')
    rewrite_tab(spreadsheet, '2025-09', rows_09, dry_run)
    if not dry_run:
        time.sleep(2)

    # ── Step 4: Create 2026 tabs ─────────────────────────────────────────
    new_months = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05']
    for month in new_months:
        json_path = os.path.join(DATA_BASE, f'{month}.json')
        if not os.path.exists(json_path):
            print(f'\n── {month}: JSON dosyası yok, atlanıyor ──')
            continue
        print(f'\n── {month}: Yeni tab oluştur ve yaz ──')
        rows = build_rows(json_path, excluded)
        print(f'  Beklenen satır: {len(rows)}')
        rewrite_tab(spreadsheet, month, rows, dry_run)
        if not dry_run:
            time.sleep(2)

    print('\nTamamlandı.')


if __name__ == '__main__':
    main()
