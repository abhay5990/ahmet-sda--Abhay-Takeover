"""Fetch + generate Eldorado templates for every game, all categories at once.

One-shot pipeline. Running this script:

  1. Builds an Eldorado SDK client from the first active Eldorado integration
     account in the DB (for auth headers).
  2. GET /api/library to list ALL services — every (game, category) pair
     (raw list saved to tmp/eldorado/library.json).
  3. For every service, fetches the two per-game endpoints:
         /api/library/{gameId}/{Category}                  -> trade environments
         /api/library/{gameId}/{Category}/attributes/offers -> offer attributes
     converts them into our consistent template schema, and writes it to:
         assets/eldorado_templates/<folder>/<slug>.json
     The raw responses are also kept under tmp/eldorado/<folder>/{gameId}/.

  Each category folder under assets/ is WIPED before writing, so the run is a
  clean from-scratch overwrite: new games appear, removed ones disappear, and
  `git diff` shows exactly what changed.

Eldorado categories (all six expose the endpoints above):
  Account            -> accounts   (also carries accountSecretDetails schema)
  CustomItem         -> items
  Currency           -> currency
  TopUp              -> topup
  RequestedBoosting  -> boosting
  GiftCard           -> giftcard

Slugs:
  - Account keeps the existing seoAlias-derived slug (e.g. "wow", "psn") so the
    curated account files and payload_pipeline doc references stay stable.
  - Other categories use a clean slug derived from gameName, so the same game
    has the same filename across every category folder.

Usage (from project root):
    python scripts/fetch_eldorado_templates.py
    python scripts/fetch_eldorado_templates.py --account eldorado-store4gamers
    python scripts/fetch_eldorado_templates.py --only currency,topup   # subset
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
LIBRARY_URL = 'https://www.eldorado.gg/api/library'
RAW_ROOT = os.path.join(PROJECT_ROOT, 'tmp', 'eldorado')
ASSETS_ROOT = os.path.join(PROJECT_ROOT, 'assets', 'eldorado_templates')
DELAY = 0.3  # seconds between games

# Eldorado category (from library[].category) -> output folder name.
CATEGORY_FOLDERS = {
    'Account': 'accounts',
    'CustomItem': 'items',
    'Currency': 'currency',
    'TopUp': 'topup',
    'RequestedBoosting': 'boosting',
    'GiftCard': 'giftcard',
}


# ── Auth / fetching ─────────────────────────────────────────────────
def find_account(slug=None):
    qs = IntegrationAccount.objects.select_related('credential').filter(
        provider='eldorado', is_active=True,
    )
    if slug:
        qs = qs.filter(slug=slug)
    account = qs.first()
    if not account:
        sys.exit(f"ERROR: no active Eldorado account found"
                 f"{f' with slug {slug}' if slug else ''}")
    if not getattr(account, 'credential', None) or not account.credential.is_active:
        sys.exit(f'ERROR: {account.slug} has no active credentials')
    return account


def make_fetcher(facade):
    """Return a get(url) -> (json|None, status) closure bound to the SDK auth."""
    transport = facade._exec._transport
    auth_headers = facade._exec.get_auth_headers()
    headers = {
        **auth_headers,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US',
    }

    def get(url, params=None):
        try:
            r = transport.request(HttpMethod.GET, url, headers=headers,
                                  params=params or {'locale': 'en-US'}, timeout=20)
            if r.is_success:
                return r.json(), r.status_code
            return None, f'http_{r.status_code}'
        except Exception as e:
            return None, f'error: {e}'

    return get


# ── Slugs ───────────────────────────────────────────────────────────
def slug_from_seo_alias(seo_alias: str) -> str:
    """Account slug: 'wow-accounts-for-sale' -> 'wow', 'psn-accounts' -> 'psn'."""
    slug = re.sub(r'-accounts?(-for-sale)?$', '', seo_alias)
    return slug or seo_alias


def slugify(text: str) -> str:
    """Clean slug from a game name: 'Honkai: Star Rail' -> 'honkai-star-rail'."""
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def slug_for(service: dict) -> str:
    if service.get('category') == 'Account':
        return slug_from_seo_alias(service.get('seoAlias', '')) or slugify(service['gameName'])
    return slugify(service['gameName'])


# ── Schema builders ─────────────────────────────────────────────────
def build_trade_environments(service_data: dict) -> list:
    """Extract visible tradeEnvironments (with nested children) from service.json."""
    envs = []
    for te in service_data.get('tradeEnvironments', []):
        if te.get('isHidden'):
            continue
        env = {'id': te['id'], 'name': te['value']}
        env_name = te.get('name', 'Device')
        if env_name != 'Device':
            env['group'] = env_name
        children = te.get('childTradeEnvironments')
        if children:
            env['children'] = [
                {'id': c['id'], 'name': c['value']}
                for c in children if not c.get('isHidden')
            ]
        envs.append(env)
    return envs


def build_attributes(attributes_offers: list) -> dict:
    """Build attributes dict keyed by offer attribute slug (what the API expects)."""
    attrs = {}
    for attr in attributes_offers or []:
        values = [
            {'id': sv['id'], 'name': sv['name']}
            for sv in attr.get('selectValues', [])
        ]
        attrs[attr['id']] = {
            'name': attr['name'],
            'type': attr.get('type', 'Select'),
            'required': attr.get('isRequired', False),
            'values': values,
        }
    return attrs


def build_details_schema(category: str) -> dict:
    """Fixed flexible-offer details schema. Account adds account-only fields."""
    details = {
        'offerTitle': {'type': 'string', 'required': True},
        'description': {'type': 'string', 'required': True},
        'pricing': {
            'type': 'object',
            'required': True,
            'fields': {
                'quantity': {'type': 'integer', 'default': 1},
                'pricePerUnit': {
                    'type': 'object',
                    'fields': {
                        'amount': {'type': 'number', 'required': True},
                        'currency': {'type': 'string', 'default': 'USD'},
                    },
                },
            },
        },
        'guaranteedDeliveryTime': {
            'type': 'string',
            'required': True,
            'values': ['Instant', 'Minute20', 'Day1'],
            'default': 'Instant',
        },
        'mainOfferImage': {
            'type': 'object',
            'required': False,
            'fields': {
                'smallImage': {'type': 'string'},
                'largeImage': {'type': 'string'},
                'originalSizeImage': {'type': 'string'},
            },
        },
        'offerImages': {
            'type': 'array',
            'required': False,
            'items': {
                'smallImage': {'type': 'string'},
                'largeImage': {'type': 'string'},
                'originalSizeImage': {'type': 'string'},
            },
        },
    }
    if category == 'Account':
        details['hasOriginalEmail'] = {
            'type': 'boolean', 'required': False, 'default': False,
        }
    return details


def build_template(service: dict, slug: str, svc_data: dict, attr_offers: list) -> dict:
    category = service['category']
    template = {
        'game_id': service['gameId'],
        'game': slug,
        'game_name': service.get('gameName', ''),
        'category': category,
        'tradeEnvironments': build_trade_environments(svc_data),
        'attributes': build_attributes(attr_offers),
        'details': build_details_schema(category),
    }
    if category == 'Account':
        template['accountSecretDetails'] = {
            'type': 'array',
            'required': False,
            'description': 'Account credentials, each entry as "login:password" '
                           'format. Not required for manual delivery offers.',
            'items': {'type': 'string'},
        }
    return template


def reset_dir(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--account', default=None,
                        help='Eldorado account slug (default: first active one)')
    parser.add_argument('--only', default=None,
                        help='Comma-separated category folders to limit to '
                             '(e.g. "currency,topup"). Default: all.')
    parser.add_argument('--game', default=None,
                        help='Filter by game ID (integer) or game name substring '
                             '(e.g. --game 570 or --game "Genshin Impact").')
    args = parser.parse_args()

    only = None
    if args.only:
        only = {x.strip().lower() for x in args.only.split(',') if x.strip()}

    game_filter = None
    if args.game:
        game_filter = args.game.strip()

    # ── Build SDK client ───────────────────────────────────────────
    account = find_account(args.account)
    facade = get_or_build_client('eldorado', account.credential)
    get = make_fetcher(facade)
    print(f'SDK client ready ({account.slug})')

    # ── Fetch library ──────────────────────────────────────────────
    print('Fetching library...')
    library, status = get(LIBRARY_URL)
    if not isinstance(library, list):
        sys.exit(f'ERROR: could not fetch library ({status})')
    print(f'Got {len(library)} services')

    os.makedirs(RAW_ROOT, exist_ok=True)
    with open(os.path.join(RAW_ROOT, 'library.json'), 'w', encoding='utf-8') as f:
        json.dump(library, f, indent=2, ensure_ascii=False)

    # ── Decide which categories to run, wipe their folders ─────────
    active_folders = {
        cat: folder for cat, folder in CATEGORY_FOLDERS.items()
        if only is None or folder in only
    }
    if not game_filter:
        for folder in active_folders.values():
            reset_dir(os.path.join(ASSETS_ROOT, folder))
            reset_dir(os.path.join(RAW_ROOT, folder))
    else:
        for folder in active_folders.values():
            os.makedirs(os.path.join(ASSETS_ROOT, folder), exist_ok=True)
            os.makedirs(os.path.join(RAW_ROOT, folder), exist_ok=True)

    work = [s for s in library if s['category'] in active_folders]

    if game_filter:
        if game_filter.isdigit():
            work = [s for s in work if str(s['gameId']) == game_filter]
        else:
            work = [s for s in work if game_filter.lower() in s.get('gameName', '').lower()]
    print(f'{len(work)} services to process across {len(active_folders)} categories\n')

    # ── Fetch + generate ───────────────────────────────────────────
    generated = 0
    failed = []
    slugs_seen = {}  # (category, slug) -> gameId, to catch collisions

    for i, service in enumerate(work, 1):
        category = service['category']
        folder = active_folders[category]
        game_id = service['gameId']
        slug = slug_for(service)
        label = f'[{i:>4}/{len(work)}] {folder}/{slug}'

        # collision guard within a category folder
        key = (category, slug)
        if key in slugs_seen:
            failed.append((folder, slug, f'duplicate slug (gameId {game_id} vs {slugs_seen[key]})'))
            print(f'  {label} -- SKIP duplicate slug (gameId {slugs_seen[key]})')
            continue

        svc_url = f'{LIBRARY_URL}/{game_id}/{category}'
        attr_url = f'{LIBRARY_URL}/{game_id}/{category}/attributes/offers'
        svc_data, st1 = get(svc_url)
        attr_offers, st2 = get(attr_url)

        if not isinstance(svc_data, dict):
            failed.append((folder, slug, f'service {st1}'))
            print(f'  {label} -- FAIL service:{st1}')
            time.sleep(DELAY)
            continue
        if not isinstance(attr_offers, list):
            attr_offers = []  # some categories legitimately have no offer attributes

        slugs_seen[key] = game_id

        # raw copies for debugging
        raw_dir = os.path.join(RAW_ROOT, folder, str(game_id))
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(service, f, indent=2, ensure_ascii=False)
        with open(os.path.join(raw_dir, 'service.json'), 'w', encoding='utf-8') as f:
            json.dump(svc_data, f, indent=2, ensure_ascii=False)
        with open(os.path.join(raw_dir, 'attributes_offers.json'), 'w', encoding='utf-8') as f:
            json.dump(attr_offers, f, indent=2, ensure_ascii=False)

        # transformed template into assets
        template = build_template(service, slug, svc_data, attr_offers)
        out_path = os.path.join(ASSETS_ROOT, folder, f'{slug}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

        generated += 1
        n_envs = len(template['tradeEnvironments'])
        n_attrs = len(template['attributes'])
        print(f'  {label} -- OK ({n_envs} envs, {n_attrs} attrs)')
        time.sleep(DELAY)

    # ── Summary ────────────────────────────────────────────────────
    print('\n=== Done ===')
    print(f'Generated: {generated}')
    print(f'Failed:    {len(failed)}')
    for folder, slug, reason in failed:
        print(f'  - {folder}/{slug}: {reason}')
    print(f'\nTemplates written under: {ASSETS_ROOT}/<folder>/')


if __name__ == '__main__':
    main()
