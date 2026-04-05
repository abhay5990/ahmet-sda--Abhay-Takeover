"""Eldorado unlinked orders credential parse report.

Reads tmp/unlinked_orders/eldorado.json, parses credentials with shared parser,
and writes a detailed report JSON.

Credential source: raw_data.accountDetails.secretDetails

Usage:
    python tests/integration/test_eldorado_credentials_report.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
from apps.sync.services.shared.credentials import parse_credentials_text

INPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'tmp', 'unlinked_orders', 'eldorado.json')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'tmp', 'unlinked_orders', 'eldorado_credentials_report.json')


def _extract_credentials_text(raw_data: dict) -> tuple[str | None, str]:
    """Extract raw credential text from Eldorado order raw_data."""
    if not raw_data:
        return None, ''

    # accountDetails.secretDetails
    account_details = raw_data.get('accountDetails') or {}
    text = account_details.get('secretDetails', '')
    if text:
        return text, 'accountDetails.secretDetails'

    return None, ''


def _extract_game_info(raw_data: dict) -> tuple[str, str]:
    """Extract game ID and name from Eldorado order."""
    offer = raw_data.get('orderOfferDetails') or {}
    game_id = str(offer.get('gameId') or '')
    game_name = offer.get('gameName') or offer.get('title') or ''
    return game_id, game_name


def _extract_state(raw_data: dict) -> str:
    return (raw_data.get('state') or {}).get('state', '')


def run():
    with open(INPUT_FILE, encoding='utf-8') as f:
        orders = json.load(f)

    parsed = []
    failures = []
    no_credentials = []

    for order in orders:
        store_order_id = order.get('store_order_id', '')
        raw_data = order.get('raw_data', {})
        state = _extract_state(raw_data)
        game_id, game_name = _extract_game_info(raw_data)

        raw_text, source = _extract_credentials_text(raw_data)

        if not raw_text:
            no_credentials.append({
                'order_id': store_order_id,
                'game_id': game_id,
                'game': game_name,
                'state': state,
            })
            continue

        try:
            result = parse_credentials_text(raw_text)
        except Exception as e:
            failures.append({
                'order_id': store_order_id,
                'game_id': game_id,
                'game': game_name,
                'state': state,
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
                'state': state,
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
            'state': state,
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
        'no_credentials': len(no_credentials),
        'parsed_ok': len(parsed),
        'parse_failed': len(failures),
        'success_rate': f'{len(parsed) * 100 / has_creds:.1f}%' if has_creds else 'N/A',
        'no_creds_by_state': {},
        'failures_by_error': {},
    }

    # State breakdown for no_credentials
    from collections import Counter
    state_counts = Counter(nc['state'] for nc in no_credentials)
    summary['no_creds_by_state'] = dict(state_counts.most_common())

    # Error type breakdown
    err_counts = Counter(f['error_type'] for f in failures)
    summary['failures_by_error'] = dict(err_counts.most_common())

    report = {
        'summary': summary,
        'failures': failures,
        'no_credentials': no_credentials,
        'parsed': parsed,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f'Total orders:       {summary["total_orders"]}')
    print(f'Has credentials:    {summary["has_credentials"]}')
    print(f'No credentials:     {summary["no_credentials"]}')
    for state, count in state_counts.most_common():
        print(f'  {state}: {count}')
    print(f'Parsed OK:          {summary["parsed_ok"]}')
    print(f'Parse failed:       {summary["parse_failed"]}')
    for err, count in err_counts.most_common():
        print(f'  {err}: {count}')
    print(f'Success rate:       {summary["success_rate"]}')
    print(f'\nReport written to: {OUTPUT_FILE}')

    if failures:
        print(f'\nFAILURES (first 20):')
        for fail in failures[:20]:
            raw_short = fail['raw_credentials'][:80].replace('\n', '\\n')
            print(f'  [{fail["game"]}] {fail["order_id"]}: {fail["error"]} — {raw_short}')


if __name__ == '__main__':
    run()
