"""Gameboost unmatched orders credential parse report.

Reads unmatched_gameboost_orders.json, parses credentials with shared parser,
and writes a detailed report JSON with:
  - parsed results (order_id, game, raw credentials, parsed fields)
  - parse failures (order_id, game, raw credentials, error info)
  - summary stats

Credential sources (checked in order):
  1. raw_payload.credentials (inline)
  2. raw_payload._credential_entries[].credentials (entry-based)

Usage:
    python tests/integration/test_credentials_parse_report.py
"""

import json
import os
import sys

# Backend path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
from apps.sync.services.shared.credentials import parse_credentials_text

INPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'unmatched_gameboost_orders.json')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'gameboost_credentials_report.json')


def _extract_credentials_text(rp: dict) -> tuple[str | None, str]:
    """Extract raw credential text from order raw_payload.

    Returns (text, source) where source is 'inline', 'entries', or 'delivery_instructions'.
    """
    # 1. Inline credentials
    text = rp.get('credentials')
    if text:
        return text, 'inline'

    # 2. _credential_entries
    entries = rp.get('_credential_entries', [])
    for entry in entries:
        cred = entry.get('credentials')
        if cred:
            return cred, 'entries'

    # 3. delivery_instructions
    di = rp.get('delivery_instructions')
    if di:
        return di, 'delivery_instructions'

    return None, ''


def run():
    with open(INPUT_FILE, encoding='utf-8') as f:
        orders = json.load(f)

    parsed = []
    failures = []
    no_credentials = []

    for order in orders:
        store_order_id = order.get('store_order_id', '')
        rp = order.get('raw_payload', {})

        # Game info
        game = rp.get('game', {})
        game_id = game.get('id') if isinstance(game, dict) else None
        game_name = game.get('name', '') if isinstance(game, dict) else ''

        # Raw credentials text — try both sources
        raw_text, source = _extract_credentials_text(rp) if isinstance(rp, dict) else (None, '')

        if not raw_text:
            no_credentials.append({
                'order_id': store_order_id,
                'game_id': game_id,
                'game': game_name,
            })
            continue

        # Parse
        try:
            result = parse_credentials_text(raw_text)
        except Exception as e:
            failures.append({
                'order_id': store_order_id,
                'game_id': game_id,
                'game': game_name,
                'raw_credentials': raw_text,
                'source': source,
                'error': str(e),
                'error_type': 'exception',
            })
            continue

        if not result.login:
            failures.append({
                'order_id': store_order_id,
                'game_id': game_id,
                'game': game_name,
                'raw_credentials': raw_text,
                'source': source,
                'error': 'login not extracted',
                'error_type': 'no_login',
            })
            continue

        entry = {
            'order_id': store_order_id,
            'game_id': game_id,
            'game': game_name,
            'source': source,
            'raw_credentials': raw_text,
            'login': result.login,
            'password': result.password,
            'email': result.email,
            'email_password': result.email_password,
            'email_login_link': result.email_login_link,
            'security_email': result.security_email,
            'security_email_password': result.security_email_password,
        }
        parsed.append(entry)

    # Summary
    total = len(orders)
    has_creds = len(parsed) + len(failures)
    summary = {
        'total_orders': total,
        'has_credentials': has_creds,
        'from_inline': sum(1 for p in parsed if p['source'] == 'inline'),
        'from_entries': sum(1 for p in parsed if p['source'] == 'entries'),
        'from_delivery_instructions': sum(1 for p in parsed if p['source'] == 'delivery_instructions'),
        'no_credentials': len(no_credentials),
        'parsed_ok': len(parsed),
        'parse_failed': len(failures),
        'success_rate': f'{len(parsed) * 100 / has_creds:.1f}%' if has_creds else 'N/A',
    }

    report = {
        'summary': summary,
        'failures': failures,
        'no_credentials': no_credentials,
        'parsed': parsed,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f'Total orders:     {summary["total_orders"]}')
    print(f'Has credentials:  {summary["has_credentials"]}')
    print(f'  from inline:    {summary["from_inline"]}')
    print(f'  from entries:   {summary["from_entries"]}')
    print(f'  from delivery:  {summary["from_delivery_instructions"]}')
    print(f'No credentials:   {summary["no_credentials"]}')
    print(f'Parsed OK:        {summary["parsed_ok"]}')
    print(f'Parse failed:     {summary["parse_failed"]}')
    print(f'Success rate:     {summary["success_rate"]}')
    print(f'\nReport written to: {OUTPUT_FILE}')

    if failures:
        print(f'\nFAILURES:')
        for fail in failures:
            print(f'  [{fail["game"]}] {fail["order_id"]}: {fail["error"]} — {fail["raw_credentials"][:80]}')


if __name__ == '__main__':
    run()
