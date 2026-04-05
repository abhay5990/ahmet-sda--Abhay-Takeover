"""Generate PlayerAuctions offer templates from raw API data.

Reads:   tmp/playerauctions/account/{gameId}/  (info.json, servers.json)
Writes:  assets/playerauctions_templates/accounts/{slug}.json

Usage (from project root):
    python scripts/generate_playerauctions_templates.py
"""

import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RAW_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'playerauctions', 'account')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'assets', 'playerauctions_templates', 'accounts')


def slugify(name: str) -> str:
    """Convert game name to a clean slug.

    'Fortnite' -> 'fortnite'
    'ARK: Survival Ascended' -> 'ark-survival-ascended'
    """
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug).strip('-')
    slug = re.sub(r'-+', '-', slug)
    return slug


def load_json(path: str):
    """Load JSON file, return None if missing or invalid."""
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def build_servers(servers_data: dict) -> list:
    """Extract servers from servers.json API response."""
    raw = servers_data.get('data', []) if isinstance(servers_data, dict) else servers_data
    servers = []
    for s in raw:
        server = {
            'id': s['id'],
            'name': s['name'],
        }
        # Include subcategories if present
        subcats = s.get('subCategorys', [])
        if subcats:
            server['subCategories'] = [
                {'id': sc['id'], 'name': sc['name']}
                for sc in subcats
            ]
        servers.append(server)
    return servers


def build_details_schema() -> dict:
    """Build the fixed details schema (same for every PA game)."""
    return {
        'title': {
            'type': 'string',
            'required': True,
        },
        'offerDesc': {
            'type': 'string',
            'required': True,
            'description': 'HTML formatted description',
        },
        'price': {
            'type': 'number',
            'required': True,
        },
        'screenShot': {
            'type': 'string',
            'required': False,
        },
        'offerDuration': {
            'type': 'integer',
            'required': True,
            'default': 30,
            'description': 'Offer duration in days',
        },
        'freeInsurance': {
            'type': 'integer',
            'required': True,
            'default': 7,
            'description': 'Free insurance in days',
        },
        'isAuto': {
            'type': 'boolean',
            'required': True,
            'default': True,
            'description': 'true = auto delivery, false = manual delivery',
        },
    }


def build_auto_delivery_schema(info: dict) -> dict:
    """Build autoDelivery schema based on game requirements."""
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

    if info.get('isSecurityQARequired'):
        schema['securityQuestion'] = {'type': 'string', 'required': True}
        schema['securityAnswer'] = {'type': 'string', 'required': True, 'encrypted': True}

    if info.get('isCDKeyRequired'):
        schema['firstCDKey'] = {'type': 'string', 'required': True}

    if info.get('isParentalPswRequired'):
        schema['parentalPassword'] = {'type': 'string', 'required': True, 'encrypted': True}

    return schema


def build_manual_delivery_schema() -> dict:
    """Build manual delivery schema."""
    return {
        'loginName': {'type': 'string', 'required': False},
        'deliveryGuarantee': {
            'type': 'integer',
            'required': True,
            'default': 4,
            'description': 'Delivery guarantee in hours',
        },
    }


def generate_template(game_id: str) -> tuple[dict | None, str | None]:
    """Generate a single template for the given gameId.

    Returns (template_dict, slug) or (None, error_message).
    """
    game_dir = os.path.join(RAW_DIR, game_id)

    info = load_json(os.path.join(game_dir, 'info.json'))
    servers_data = load_json(os.path.join(game_dir, 'servers.json'))

    if not info:
        return None, 'missing info.json'
    if not servers_data:
        return None, 'missing servers.json'

    # Slug from seoName or gameName
    seo_name = info.get('seoName', '') or info.get('gameName', '')
    slug = slugify(seo_name)
    if not slug:
        return None, 'empty slug'

    # Servers
    servers = build_servers(servers_data)

    template = {
        'game_id': info['gameId'],
        'game': slug,
        'game_name': info.get('gameName', ''),
        'seo_name': info.get('seoName', ''),
        'servers': servers,
        'requiredFields': {
            'securityQA': bool(info.get('isSecurityQARequired')),
            'cdKey': bool(info.get('isCDKeyRequired')),
            'parentalPassword': bool(info.get('isParentalPswRequired')),
        },
        'details': build_details_schema(),
        'autoDelivery': build_auto_delivery_schema(info),
        'manualDelivery': build_manual_delivery_schema(),
    }

    return template, slug


def main():
    if not os.path.isdir(RAW_DIR):
        print(f'ERROR: Raw data directory not found: {RAW_DIR}')
        print('Run fetch_playerauctions_account_data.py first.')
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    game_ids = sorted(
        [d for d in os.listdir(RAW_DIR) if os.path.isdir(os.path.join(RAW_DIR, d))],
        key=lambda x: int(x) if x.isdigit() else 0,
    )

    print(f'Found {len(game_ids)} game directories')

    stats = {'ok': 0, 'fail': 0}
    slugs_seen = {}

    for game_id in game_ids:
        template, slug_or_error = generate_template(game_id)

        if template is None:
            stats['fail'] += 1
            print(f'  FAIL {game_id:>5}: {slug_or_error}')
            continue

        slug = slug_or_error

        # Duplicate slug check
        if slug in slugs_seen:
            stats['fail'] += 1
            print(f'  FAIL {game_id:>5}: duplicate slug "{slug}" (already used by gameId {slugs_seen[slug]})')
            continue

        slugs_seen[slug] = game_id

        out_path = os.path.join(OUTPUT_DIR, f'{slug}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

        n_servers = len(template['servers'])
        has_subcats = any('subCategories' in s for s in template['servers'])
        extra = ' (has subcats)' if has_subcats else ''
        stats['ok'] += 1
        print(f'  OK   {game_id:>5}: {slug}.json ({n_servers} servers{extra})')

    print(f'\n=== Done ===')
    print(f'Generated: {stats["ok"]}')
    print(f'Failed:    {stats["fail"]}')
    print(f'\nTemplates saved to: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
