"""Generate Eldorado offer templates from raw API data.

Reads:   tmp/eldorado/account/{gameId}/  (info.json, service.json, attributes_offers.json)
Writes:  assets/eldorado_templates/accounts/{slug}.json

Usage (from project root):
    python scripts/generate_eldorado_templates.py
"""

import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RAW_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'eldorado', 'account')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'assets', 'eldorado_templates', 'accounts')


def slug_from_seo_alias(seo_alias: str) -> str:
    """Extract clean slug from Eldorado seoAlias.

    'fortnite-accounts-for-sale' -> 'fortnite'
    'rainbow-six-siege-accounts' -> 'rainbow-six-siege'
    """
    slug = re.sub(r'-accounts?(-for-sale)?$', '', seo_alias)
    return slug or seo_alias


def load_json(path: str):
    """Load JSON file, return None if missing or invalid."""
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def build_trade_environments(service_data: dict) -> list:
    """Extract tradeEnvironments from service.json."""
    raw = service_data.get('tradeEnvironments', [])
    envs = []
    for te in raw:
        if te.get('isHidden'):
            continue
        env = {'id': te['id'], 'name': te['value']}
        # Include environment group name if not "Device" (some games have Region, Server, etc.)
        env_name = te.get('name', 'Device')
        if env_name != 'Device':
            env['group'] = env_name
        # Handle nested child environments
        children = te.get('childTradeEnvironments')
        if children:
            env['children'] = [
                {'id': c['id'], 'name': c['value']}
                for c in children
                if not c.get('isHidden')
            ]
        envs.append(env)
    return envs


def build_attributes(attributes_offers: list) -> dict:
    """Build attributes dict from attributes_offers.json.

    Uses the offer attribute slugs as keys (these are what the API expects).
    """
    attrs = {}
    for attr in attributes_offers:
        attr_id = attr['id']  # e.g. "fortnite-account-type"
        values = [
            {'id': sv['id'], 'name': sv['name']}
            for sv in attr.get('selectValues', [])
        ]
        attrs[attr_id] = {
            'name': attr['name'],
            'type': attr.get('type', 'Select'),
            'required': attr.get('isRequired', False),
            'values': values,
        }
    return attrs


def build_details_schema() -> dict:
    """Build the fixed details schema (same for every game)."""
    return {
        'offerTitle': {
            'type': 'string',
            'required': True,
        },
        'description': {
            'type': 'string',
            'required': True,
        },
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
        'hasOriginalEmail': {
            'type': 'boolean',
            'required': False,
            'default': False,
        },
    }


def build_account_secret_details_schema() -> dict:
    """Build the accountSecretDetails schema."""
    return {
        'type': 'array',
        'required': False,
        'description': 'Account credentials, each entry as "login:password" format. Not required for manual delivery offers.',
        'items': {'type': 'string'},
    }


def generate_template(game_id: str) -> tuple[dict | None, str | None]:
    """Generate a single template for the given gameId.

    Returns (template_dict, slug) or (None, error_message).
    """
    game_dir = os.path.join(RAW_DIR, game_id)

    info = load_json(os.path.join(game_dir, 'info.json'))
    service = load_json(os.path.join(game_dir, 'service.json'))
    attributes_offers = load_json(os.path.join(game_dir, 'attributes_offers.json'))

    if not info:
        return None, 'missing info.json'
    if not service:
        return None, 'missing service.json'

    # Slug
    seo_alias = info.get('seoAlias', '')
    slug = slug_from_seo_alias(seo_alias)
    if not slug:
        return None, 'empty slug'

    # Trade environments
    trade_envs = build_trade_environments(service)

    # Attributes (may be empty list or missing)
    attrs = build_attributes(attributes_offers or [])

    template = {
        'game_id': info['gameId'],
        'game': slug,
        'game_name': info.get('gameName', ''),
        'category': info.get('category', 'Account'),
        'tradeEnvironments': trade_envs,
        'attributes': attrs,
        'details': build_details_schema(),
        'accountSecretDetails': build_account_secret_details_schema(),
    }

    return template, slug


def main():
    if not os.path.isdir(RAW_DIR):
        print(f'ERROR: Raw data directory not found: {RAW_DIR}')
        print('Run fetch_eldorado_account_data.py first.')
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    game_ids = sorted(
        [d for d in os.listdir(RAW_DIR) if os.path.isdir(os.path.join(RAW_DIR, d))],
        key=lambda x: int(x) if x.isdigit() else 0,
    )

    print(f'Found {len(game_ids)} game directories')

    stats = {'ok': 0, 'skip': 0, 'fail': 0}
    slugs_seen = {}

    for game_id in game_ids:
        template, slug_or_error = generate_template(game_id)

        if template is None:
            stats['fail'] += 1
            print(f'  FAIL {game_id:>4}: {slug_or_error}')
            continue

        slug = slug_or_error

        # Duplicate slug check
        if slug in slugs_seen:
            stats['fail'] += 1
            print(f'  FAIL {game_id:>4}: duplicate slug "{slug}" (already used by gameId {slugs_seen[slug]})')
            continue

        slugs_seen[slug] = game_id

        out_path = os.path.join(OUTPUT_DIR, f'{slug}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

        n_envs = len(template['tradeEnvironments'])
        n_attrs = len(template['attributes'])
        stats['ok'] += 1
        print(f'  OK   {game_id:>4}: {slug}.json ({n_envs} envs, {n_attrs} attrs)')

    print(f'\n=== Done ===')
    print(f'Generated: {stats["ok"]}')
    print(f'Failed:    {stats["fail"]}')
    print(f'\nTemplates saved to: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
