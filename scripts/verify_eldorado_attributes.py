"""Verify Eldorado offer attributes against local templates.

Fetches the public library endpoint for each Account game and compares
the returned attribute IDs/values with our stored templates.

Reports:
  - Missing attributes (in API but not in template)
  - Extra attributes (in template but not in API)
  - Changed values (value IDs that differ)
  - Games with no template

Usage (from project root):
    python scripts/verify_eldorado_attributes.py
    python scripts/verify_eldorado_attributes.py --game-id 32       # Single game
    python scripts/verify_eldorado_attributes.py --save              # Save fetched data
"""

import argparse
import json
import os
import re
import sys
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SERVICES_PATH = os.path.join(PROJECT_ROOT, '_data_samples', 'eldorado', 'services.json')
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, 'assets', 'eldorado_templates', 'accounts')
RAW_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'eldorado', 'account')
SAVE_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'eldorado', 'attributes_check')

BASE_URL = 'https://www.eldorado.gg/api/library'
DELAY = 0.3

HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
}


def slug_from_seo_alias(seo_alias: str) -> str:
    slug = re.sub(r'-accounts?(-for-sale)?$', '', seo_alias)
    return slug or seo_alias


def load_account_games():
    with open(SERVICES_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return [g for g in data if g.get('category') == 'Account']


def load_template(slug: str) -> dict | None:
    path = os.path.join(TEMPLATES_DIR, f'{slug}.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def fetch_attributes(game_id: str) -> list | None:
    """Fetch offer attributes from public library endpoint."""
    url = f'{BASE_URL}/{game_id}/Account/attributes/offers'
    try:
        resp = requests.get(url, headers=HEADERS, params={'locale': 'en-US'}, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f'    HTTP {resp.status_code}')
        return None
    except Exception as e:
        print(f'    ERROR: {e}')
        return None


def compare_attributes(template_attrs: dict, api_attrs: list) -> dict:
    """Compare template attributes with API response.

    Returns dict with keys: missing, extra, changed, matched.
    """
    # Build lookup from API response
    api_lookup: dict[str, dict] = {}
    for attr in api_attrs:
        attr_id = attr.get('id', '')
        values = [sv['id'] for sv in attr.get('selectValues', [])]
        api_lookup[attr_id] = {
            'name': attr.get('name', ''),
            'type': attr.get('type', 'Select'),
            'required': attr.get('isRequired', False),
            'values': values,
            'raw': attr,
        }

    result = {'missing': [], 'extra': [], 'changed': [], 'matched': []}

    # Check API attrs against template
    for attr_id, api_info in api_lookup.items():
        if attr_id not in template_attrs:
            result['missing'].append({
                'id': attr_id,
                'name': api_info['name'],
                'values': api_info['values'],
            })
            continue

        tmpl = template_attrs[attr_id]
        tmpl_values = {v['id'] for v in tmpl.get('values', [])}
        api_values = set(api_info['values'])

        if tmpl_values != api_values:
            result['changed'].append({
                'id': attr_id,
                'name': api_info['name'],
                'added': sorted(api_values - tmpl_values),
                'removed': sorted(tmpl_values - api_values),
            })
        else:
            result['matched'].append(attr_id)

    # Check template attrs not in API
    for attr_id in template_attrs:
        if attr_id not in api_lookup:
            result['extra'].append({
                'id': attr_id,
                'name': template_attrs[attr_id].get('name', ''),
            })

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game-id', type=str, default=None,
                        help='Check single game ID (e.g. "32" for Valorant)')
    parser.add_argument('--save', action='store_true',
                        help='Save fetched API responses to tmp/')
    args = parser.parse_args()

    games = load_account_games()
    print(f'Loaded {len(games)} Account games from services.json')

    if args.game_id:
        games = [g for g in games if str(g['gameId']) == args.game_id]
        if not games:
            print(f'ERROR: Game ID {args.game_id} not found')
            sys.exit(1)

    if args.save:
        os.makedirs(SAVE_DIR, exist_ok=True)

    stats = {
        'ok': 0, 'no_template': 0, 'fetch_fail': 0,
        'has_changes': 0, 'has_missing': 0, 'has_extra': 0,
    }
    issues = []

    for i, game in enumerate(games, 1):
        game_id = str(game['gameId'])
        game_name = game.get('gameName', '?')
        seo_alias = game.get('seoAlias', '')
        slug = slug_from_seo_alias(seo_alias)

        label = f'[{i:>3}/{len(games)}] {game_id:>4} {game_name}'

        # Load template
        template = load_template(slug)
        if not template:
            stats['no_template'] += 1
            print(f'  SKIP {label} — no template ({slug}.json)')
            continue

        # Fetch from API
        api_attrs = fetch_attributes(game_id)
        if api_attrs is None:
            stats['fetch_fail'] += 1
            print(f'  FAIL {label} — fetch failed')
            continue

        if args.save:
            save_path = os.path.join(SAVE_DIR, f'{slug}_attributes.json')
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(api_attrs, f, indent=2, ensure_ascii=False)

        # Compare
        diff = compare_attributes(template.get('attributes', {}), api_attrs)

        has_issues = diff['missing'] or diff['extra'] or diff['changed']
        if has_issues:
            if diff['missing']:
                stats['has_missing'] += 1
            if diff['extra']:
                stats['has_extra'] += 1
            if diff['changed']:
                stats['has_changes'] += 1

            issues.append({
                'game_id': game_id,
                'game_name': game_name,
                'slug': slug,
                'diff': diff,
            })
            print(f'  DIFF {label} — '
                  f'missing:{len(diff["missing"])} '
                  f'extra:{len(diff["extra"])} '
                  f'changed:{len(diff["changed"])} '
                  f'matched:{len(diff["matched"])}')
        else:
            stats['ok'] += 1
            print(f'  OK   {label} ({len(diff["matched"])} attrs matched)')

        time.sleep(DELAY)

    # Summary
    print(f'\n{"="*60}')
    print(f'  SUMMARY')
    print(f'{"="*60}')
    print(f'  Matched:      {stats["ok"]}')
    print(f'  No template:  {stats["no_template"]}')
    print(f'  Fetch failed: {stats["fetch_fail"]}')
    print(f'  Has changes:  {stats["has_changes"]}')
    print(f'  Has missing:  {stats["has_missing"]}')
    print(f'  Has extra:    {stats["has_extra"]}')

    if issues:
        print(f'\n{"="*60}')
        print(f'  DETAILS')
        print(f'{"="*60}')
        for item in issues:
            diff = item['diff']
            print(f'\n  {item["game_name"]} (gameId={item["game_id"]}, slug={item["slug"]})')
            if diff['missing']:
                print(f'    MISSING (in API, not in template):')
                for m in diff['missing']:
                    print(f'      - {m["id"]} ({m["name"]}): {m["values"][:5]}')
            if diff['extra']:
                print(f'    EXTRA (in template, not in API):')
                for e in diff['extra']:
                    print(f'      - {e["id"]} ({e["name"]})')
            if diff['changed']:
                print(f'    CHANGED values:')
                for c in diff['changed']:
                    if c['added']:
                        print(f'      - {c["id"]}: +added={c["added"][:5]}')
                    if c['removed']:
                        print(f'      - {c["id"]}: -removed={c["removed"][:5]}')

    # Save report
    if args.save and issues:
        report_path = os.path.join(SAVE_DIR, '_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(issues, f, indent=2, ensure_ascii=False)
        print(f'\n  Report saved to: {report_path}')


if __name__ == '__main__':
    main()
