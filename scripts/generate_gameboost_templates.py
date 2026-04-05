"""Generate Gameboost offer templates from raw API data.

Reads:   tmp/gameboost/accounts/{slug}.json  (raw API responses)
Writes:  assets/gameboost_templates/accounts/{slug}.json

Converts raw Gameboost template format (sample values + condition rules)
into a consistent schema format matching Eldorado/PlayerAuctions templates.

Usage (from project root):
    python scripts/generate_gameboost_templates.py
"""

import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RAW_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'gameboost', 'accounts')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'assets', 'gameboost_templates', 'accounts')


def load_json(path: str):
    """Load JSON file, return None if missing or invalid."""
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def is_optional_sample(value) -> bool:
    """Check if a sample value indicates an optional field."""
    if isinstance(value, str) and value.startswith('(optional)'):
        return True
    return False


def convert_condition(field_name: str, field_def: dict) -> dict:
    """Convert Gameboost condition format to schema format.

    Examples:
        {"condition": "string", "values": [...]}  -> {"type": "string", "required": false, "values": [...]}
        {"condition": "required", "values": [...]} -> {"type": "string", "required": true, "values": [...]}
        {"condition": "boolean"}                   -> {"type": "boolean", "required": false}
        {"condition": "min:0"}                     -> {"type": "integer", "required": false, "min": 0}
        {"condition": "max:100"}                   -> {"type": "number", "required": false, "max": 100}
        {"condition": "integer", "values": [...]}  -> {"type": "integer", "required": false, "values": [...]}
        {"condition": "array"}                     -> {"type": "array", "required": false}
    """
    condition = field_def.get('condition', 'string')
    values = field_def.get('values')
    schema = {}

    # Parse condition
    min_match = re.match(r'min:(\d+)', condition)
    max_match = re.match(r'max:(\d+)', condition)

    if condition == 'boolean':
        schema['type'] = 'boolean'
        schema['required'] = False
    elif condition == 'array':
        schema['type'] = 'array'
        schema['required'] = False
    elif condition == 'integer':
        schema['type'] = 'integer'
        schema['required'] = False
        if values:
            schema['values'] = values
    elif min_match:
        schema['type'] = 'integer'
        schema['required'] = False
        schema['min'] = int(min_match.group(1))
    elif max_match:
        schema['type'] = 'number'
        schema['required'] = False
        schema['max'] = int(max_match.group(1))
    elif condition == 'required':
        schema['type'] = 'string'
        schema['required'] = True
        if values:
            schema['values'] = values
    else:
        # "string" or unknown
        schema['type'] = 'string'
        schema['required'] = False
        if values:
            schema['values'] = values

    return schema


def build_account_data(raw_account_data: dict) -> dict:
    """Convert account_data section, merging array + .* patterns."""
    result = {}
    # Collect .* fields for merging
    array_items = {}
    for key, value in raw_account_data.items():
        if '.*' in key:
            base_key = key.replace('.*', '')
            array_items[base_key] = value
            continue
        result[key] = convert_condition(key, value)

    # Merge array items into their parent
    for base_key, item_def in array_items.items():
        if base_key in result and result[base_key].get('type') == 'array':
            result[base_key]['items'] = convert_condition(base_key, item_def)

    return result


def build_fixed_fields(raw: dict) -> dict:
    """Convert fixed template fields (title, price, etc.) to schema format."""
    fields = {}

    # String fields
    string_fields = [
        'title', 'slug', 'login', 'password',
        'email_login', 'email_password',
        'description', 'dump', 'delivery_instructions',
    ]
    for name in string_fields:
        if name not in raw:
            continue
        value = raw[name]
        optional = is_optional_sample(value)
        fields[name] = {
            'type': 'string',
            'required': not optional,
        }

    # Price
    if 'price' in raw:
        fields['price'] = {
            'type': 'number',
            'required': True,
        }

    # is_manual
    if 'is_manual' in raw:
        fields['is_manual'] = {
            'type': 'boolean',
            'required': False,
            'default': False,
        }

    # delivery_time
    if 'delivery_time' in raw:
        fields['delivery_time'] = {
            'type': 'object',
            'required': True,
            'fields': {
                'duration': {'type': 'integer', 'required': True},
                'unit': {
                    'type': 'string',
                    'required': True,
                    'values': ['minutes', 'hours', 'days'],
                },
            },
        }

    # image_urls
    if 'image_urls' in raw:
        fields['image_urls'] = {
            'type': 'array',
            'required': False,
            'items': {'type': 'string'},
        }

    return fields


def generate_template(slug: str, raw: dict) -> dict:
    """Generate a single template from raw API data."""
    template_data = raw.get('template', raw)

    result = {
        'game': template_data.get('game', slug),
    }

    # Fixed fields → details schema
    result['details'] = build_fixed_fields(template_data)

    # account_data → game-specific fields
    raw_account_data = template_data.get('account_data')
    if raw_account_data:
        result['account_data'] = build_account_data(raw_account_data)

    # game_items → keep as-is
    game_items = template_data.get('game_items')
    if game_items:
        result['game_items'] = game_items

    return result


def main():
    if not os.path.isdir(RAW_DIR):
        print(f'ERROR: Raw data directory not found: {RAW_DIR}')
        print('Run fetch_gameboost_templates.py first.')
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    raw_files = sorted([
        f for f in os.listdir(RAW_DIR)
        if f.endswith('.json')
    ])

    print(f'Found {len(raw_files)} raw templates')

    stats = {'ok': 0, 'fail': 0}

    for filename in raw_files:
        slug = filename.replace('.json', '')
        raw = load_json(os.path.join(RAW_DIR, filename))

        if not raw:
            stats['fail'] += 1
            print(f'  FAIL: {filename} (empty or invalid)')
            continue

        try:
            template = generate_template(slug, raw)
        except Exception as e:
            stats['fail'] += 1
            print(f'  FAIL: {filename} ({e})')
            continue

        out_path = os.path.join(OUTPUT_DIR, filename)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

        n_account = len(template.get('account_data', {}))
        n_items = len(template.get('game_items', {}))
        extra = f', {n_items} item cats' if n_items else ''
        stats['ok'] += 1
        print(f'  OK  : {slug}.json ({n_account} account fields{extra})')

    print(f'\n=== Done ===')
    print(f'Generated: {stats["ok"]}')
    print(f'Failed:    {stats["fail"]}')
    print(f'\nTemplates saved to: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
