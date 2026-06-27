"""Fetch + generate PlayerAuctions templates for every game, all at once.

One-shot pipeline. Running this script:

  1. Builds a PlayerAuctions SDK client from the first active PA integration
     account in the DB. Auth is handled by the SDK (it refreshes the JWT via the
     local token microservice on demand — no manual cookies needed).
  2. GET /api/games to list ALL games and their product types
     (raw list saved to tmp/playerauctions/games.json).
  3. For every game, for each supported category, fetches the real per-game data,
     converts it into our template schema, and writes it to:
         assets/playerauctions_templates/<folder>/<slug>.json
     Raw responses are kept under tmp/playerauctions/<folder>/{gameId}/.

  Each category folder under assets/ is WIPED before writing, so the run is a
  clean from-scratch overwrite: new games appear, removed ones disappear, and
  `git diff` shows exactly what changed.

Categories (PA productType token -> folder, both backed by real API data):
  account  -> accounts   servers (realms) + required-field flags + delivery schema
  item     -> items      items/categories taxonomy + servers

NOTE on the other product types (currency / topup / powerleveling): PlayerAuctions
exposes no category-specific structured endpoint for them — `{cat}/servers` just
echoes the same shared realm list, and there is no offer schema for them in this
codebase. They are intentionally not generated. Pass --only to limit categories.

Usage (from project root):
    python scripts/fetch_playerauctions_templates.py
    python scripts/fetch_playerauctions_templates.py --account playerauctions-vapenation234
    python scripts/fetch_playerauctions_templates.py --only accounts
"""

import argparse
import json
import os
import re
import shutil
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
from apis_sdk.core.enums import HttpMethod  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
OFFER_API = 'https://offer-api.playerauctions.com'
GAMES_URL = f'{OFFER_API}/api/games'
RAW_ROOT = os.path.join(PROJECT_ROOT, 'tmp', 'playerauctions')
ASSETS_ROOT = os.path.join(PROJECT_ROOT, 'assets', 'playerauctions_templates')
DELAY = 0.25  # seconds between games

# productType token (in games[].productType, comma-separated) -> folder name.
CATEGORY_FOLDERS = {
    'account': 'accounts',
    'item': 'items',
}


# ── Auth / fetching ─────────────────────────────────────────────────
def find_account(slug=None):
    qs = IntegrationAccount.objects.select_related('credential').filter(
        provider='playerauctions', is_active=True,
    )
    if slug:
        qs = qs.filter(slug=slug)
    account = qs.first()
    if not account:
        sys.exit(f"ERROR: no active PlayerAuctions account found"
                 f"{f' with slug {slug}' if slug else ''}")
    if not getattr(account, 'credential', None) or not account.credential.is_active:
        sys.exit(f'ERROR: {account.slug} has no active credentials')
    return account


def make_fetcher(facade):
    """Return get(url) -> (data|None, status). Auth headers are refreshed by the
    SDK on each call (get_auth_headers refreshes the JWT when needed)."""
    transport = facade._client._transport
    base = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US',
        'origin': 'https://member.playerauctions.com',
    }

    def get(url, params=None):
        headers = {**facade._exec.get_auth_headers(), **base}
        try:
            r = transport.request(HttpMethod.GET, url, headers=headers,
                                  params=params, timeout=20)
            if r.is_success:
                return r.json(), r.status_code
            return None, f'http_{r.status_code}'
        except Exception as e:
            return None, f'error: {e}'

    return get


def unwrap(payload):
    """PA wraps responses as {isSuccess, code, data}. Return the data list/obj."""
    if isinstance(payload, dict) and 'data' in payload:
        return payload['data']
    return payload


# ── Slugs ───────────────────────────────────────────────────────────
def slugify(name: str) -> str:
    """'ARK: Survival Ascended' -> 'ark-survival-ascended'."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug).strip('-')
    slug = re.sub(r'-+', '-', slug)
    return slug


def game_slug(game: dict) -> str:
    return slugify(game.get('seoName', '') or game.get('gameName', ''))


def has_product(game: dict, token: str) -> bool:
    tokens = {t.strip().lower() for t in (game.get('productType') or '').split(',')}
    return token in tokens


# ── Shared builders ─────────────────────────────────────────────────
def build_servers(servers_data) -> list:
    servers = []
    for s in unwrap(servers_data) or []:
        server = {'id': s['id'], 'name': s['name']}
        subcats = s.get('subCategorys') or []
        if subcats:
            server['subCategories'] = [
                {'id': sc['id'], 'name': sc['name']} for sc in subcats
            ]
        servers.append(server)
    return servers


def build_item_categories(categories_data) -> list:
    cats = []
    for c in unwrap(categories_data) or []:
        cat = {'id': c['id'], 'name': c['name'], 'seoName': c.get('seoName', '')}
        subs = c.get('subCategorys') or []
        if subs:
            cat['subCategories'] = [
                {'id': sc['id'], 'name': sc['name'], 'seoName': sc.get('seoName', '')}
                for sc in subs
            ]
        cats.append(cat)
    return cats


# ── Account template (reproduces the existing accounts/ format exactly) ──
def build_account_details_schema() -> dict:
    return {
        'title': {'type': 'string', 'required': True},
        'offerDesc': {'type': 'string', 'required': True,
                      'description': 'HTML formatted description'},
        'price': {'type': 'number', 'required': True},
        'screenShot': {'type': 'string', 'required': False},
        'offerDuration': {'type': 'integer', 'required': True, 'default': 30,
                          'description': 'Offer duration in days'},
        'freeInsurance': {'type': 'integer', 'required': True, 'default': 7,
                          'description': 'Free insurance in days'},
        'isAuto': {'type': 'boolean', 'required': True, 'default': True,
                   'description': 'true = auto delivery, false = manual delivery'},
    }


def build_auto_delivery_schema(game: dict) -> dict:
    schema = {
        'loginName': {'type': 'string', 'required': True},
        'password': {'type': 'string', 'required': True, 'encrypted': True},
        'characterName': {'type': 'string', 'required': False},
        'instruction': {'type': 'string', 'required': False},
        'ownerInfo': {
            'type': 'object',
            'required': True,
            'fields': {
                'firstName': {'type': 'string'},
                'lastName': {'type': 'string'},
                'phone': {'type': 'string'},
                'email': {'type': 'string'},
                'city': {'type': 'string'},
                'country': {'type': 'string'},
            },
        },
    }
    if game.get('isSecurityQARequired'):
        schema['securityQuestion'] = {'type': 'string', 'required': True}
        schema['securityAnswer'] = {'type': 'string', 'required': True, 'encrypted': True}
    if game.get('isCDKeyRequired'):
        schema['firstCDKey'] = {'type': 'string', 'required': True}
    if game.get('isParentalPswRequired'):
        schema['parentalPassword'] = {'type': 'string', 'required': True, 'encrypted': True}
    return schema


def build_manual_delivery_schema() -> dict:
    return {
        'loginName': {'type': 'string', 'required': False},
        'deliveryGuarantee': {'type': 'integer', 'required': True, 'default': 4,
                              'description': 'Delivery guarantee in hours'},
    }


def build_account_template(game: dict, servers_data) -> dict:
    return {
        'game_id': game['gameId'],
        'game': game_slug(game),
        'game_name': game.get('gameName', ''),
        'seo_name': game.get('seoName', ''),
        'servers': build_servers(servers_data),
        'requiredFields': {
            'securityQA': bool(game.get('isSecurityQARequired')),
            'cdKey': bool(game.get('isCDKeyRequired')),
            'parentalPassword': bool(game.get('isParentalPswRequired')),
        },
        'details': build_account_details_schema(),
        'autoDelivery': build_auto_delivery_schema(game),
        'manualDelivery': build_manual_delivery_schema(),
    }


# ── Item template (real items/categories taxonomy + servers) ─────────
def build_item_details_schema() -> dict:
    return {
        'title': {'type': 'string', 'required': True},
        'offerDesc': {'type': 'string', 'required': True,
                      'description': 'HTML formatted description'},
        'price': {'type': 'number', 'required': True,
                  'description': 'Price per unit'},
        'quantity': {'type': 'integer', 'required': True, 'default': 1,
                     'description': 'Stock quantity'},
        'minUnit': {'type': 'integer', 'required': False, 'default': 1,
                    'description': 'Minimum units per purchase'},
        'offerDuration': {'type': 'integer', 'required': True, 'default': 30,
                          'description': 'Offer duration in days'},
        'deliveryGuarantee': {'type': 'integer', 'required': True, 'default': 4,
                              'description': 'Delivery guarantee in hours'},
    }


def build_item_template(game: dict, categories_data, servers_data) -> dict:
    return {
        'game_id': game['gameId'],
        'game': game_slug(game),
        'game_name': game.get('gameName', ''),
        'seo_name': game.get('seoName', ''),
        'currencyName': game.get('curName', ''),
        'categories': build_item_categories(categories_data),
        'servers': build_servers(servers_data),
        'details': build_item_details_schema(),
    }


def reset_dir(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--account', default=None,
                        help='PA account slug (default: first active one)')
    parser.add_argument('--only', default=None,
                        help='Comma-separated folders to limit to (accounts,items).')
    args = parser.parse_args()

    only = None
    if args.only:
        only = {x.strip().lower() for x in args.only.split(',') if x.strip()}

    active = {tok: folder for tok, folder in CATEGORY_FOLDERS.items()
              if only is None or folder in only}
    if not active:
        sys.exit(f'ERROR: --only matched no known folder (have: {list(CATEGORY_FOLDERS.values())})')

    # ── Build SDK client ───────────────────────────────────────────
    account = find_account(args.account)
    facade = get_or_build_client('playerauctions', account.credential)
    get = make_fetcher(facade)
    print(f'SDK client ready ({account.slug})')

    # ── Fetch games ────────────────────────────────────────────────
    print('Fetching games...')
    games_payload, status = get(GAMES_URL)
    games = unwrap(games_payload)
    if not isinstance(games, list):
        sys.exit(f'ERROR: could not fetch games list ({status})')
    print(f'Got {len(games)} games')

    os.makedirs(RAW_ROOT, exist_ok=True)
    with open(os.path.join(RAW_ROOT, 'games.json'), 'w', encoding='utf-8') as f:
        json.dump(games, f, indent=2, ensure_ascii=False)

    # ── Wipe target folders ────────────────────────────────────────
    for folder in active.values():
        reset_dir(os.path.join(ASSETS_ROOT, folder))
        reset_dir(os.path.join(RAW_ROOT, folder))

    # ── Build work list ────────────────────────────────────────────
    work = []  # (token, folder, game)
    for game in games:
        for token, folder in active.items():
            if has_product(game, token):
                work.append((token, folder, game))
    print(f'{len(work)} (game, category) pairs to process\n')

    generated = 0
    failed = []
    slugs_seen = {}  # (folder, slug) -> gameId

    for i, (token, folder, game) in enumerate(work, 1):
        gid = game['gameId']
        slug = game_slug(game)
        label = f'[{i:>4}/{len(work)}] {folder}/{slug}'

        if not slug:
            failed.append((folder, str(gid), 'empty slug'))
            print(f'  {label} -- SKIP empty slug')
            continue
        key = (folder, slug)
        if key in slugs_seen:
            failed.append((folder, slug, f'duplicate slug (gameId {gid} vs {slugs_seen[key]})'))
            print(f'  {label} -- SKIP duplicate (gameId {slugs_seen[key]})')
            continue

        raw_dir = os.path.join(RAW_ROOT, folder, str(gid))
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(game, f, indent=2, ensure_ascii=False)

        if token == 'account':
            servers_data, st = get(f'{GAMES_URL}/{gid}/account/servers')
            if servers_data is None:
                failed.append((folder, slug, f'servers {st}'))
                print(f'  {label} -- FAIL servers:{st}')
                time.sleep(DELAY)
                continue
            with open(os.path.join(raw_dir, 'servers.json'), 'w', encoding='utf-8') as f:
                json.dump(servers_data, f, indent=2, ensure_ascii=False)
            template = build_account_template(game, servers_data)
            extra = f"{len(template['servers'])} servers"

        else:  # item
            categories_data, st1 = get(f'{GAMES_URL}/{gid}/items/categories')
            servers_data, st2 = get(f'{GAMES_URL}/{gid}/item/servers')
            if categories_data is None and servers_data is None:
                failed.append((folder, slug, f'categories {st1} / servers {st2}'))
                print(f'  {label} -- FAIL categories:{st1} servers:{st2}')
                time.sleep(DELAY)
                continue
            with open(os.path.join(raw_dir, 'categories.json'), 'w', encoding='utf-8') as f:
                json.dump(categories_data, f, indent=2, ensure_ascii=False)
            with open(os.path.join(raw_dir, 'servers.json'), 'w', encoding='utf-8') as f:
                json.dump(servers_data, f, indent=2, ensure_ascii=False)
            template = build_item_template(game, categories_data, servers_data)
            extra = f"{len(template['categories'])} cats, {len(template['servers'])} servers"

        slugs_seen[key] = gid
        out_path = os.path.join(ASSETS_ROOT, folder, f'{slug}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

        generated += 1
        print(f'  {label} -- OK ({extra})')
        time.sleep(DELAY)

    # ── Summary ────────────────────────────────────────────────────
    print('\n=== Done ===')
    print(f'Generated: {generated}')
    print(f'Failed/skipped: {len(failed)}')
    for folder, slug, reason in failed:
        print(f'  - {folder}/{slug}: {reason}')
    print(f'\nTemplates written under: {ASSETS_ROOT}/<folder>/')


if __name__ == '__main__':
    main()
