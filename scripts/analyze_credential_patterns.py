"""Analyze credential text patterns from the credentials report JSONs.

Reads the credential report files and categorizes raw_text patterns
to understand what formats exist and how well the parser handles them.

Usage (from project root):
    python scripts/analyze_credential_patterns.py

Output: tmp/credentials_report/pattern_analysis.json
"""

import json
import os
import re
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
REPORT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'credentials_report')


def classify_pattern(raw_text: str) -> str:
    """Classify the format pattern of a credential text."""
    if not raw_text:
        return 'EMPTY'

    lines = raw_text.strip().split('\n')
    has_arrow = '->' in raw_text
    has_colon_label = bool(re.search(r'(?i)(login|password|mail|email|account)\s*:', raw_text))
    has_tab = '\t' in raw_text
    has_section_header = bool(re.search(r'(?i)(details|info)\s*:', raw_text))

    # Build a structural fingerprint
    line_types = []
    for line in lines:
        line_s = line.strip()
        if not line_s:
            line_types.append('BLANK')
        elif '->' in line_s:
            line_types.append('ARROW')
        elif re.match(r'(?i)^(login|username|account|epic|riot|steam|supercell|ubisoft|device)\b', line_s):
            if ':' in line_s:
                line_types.append('LABEL_COLON')
            else:
                line_types.append('LABEL_NO_COLON')
        elif re.match(r'(?i)^(e?-?mail|security|reserve|2fa)\b', line_s):
            if ':' in line_s:
                line_types.append('MAIL_LABEL_COLON')
            else:
                line_types.append('MAIL_LABEL_NO_COLON')
        elif re.match(r'(?i)^(password|pass)\b', line_s):
            if ':' in line_s:
                line_types.append('PASS_LABEL_COLON')
            else:
                line_types.append('PASS_LABEL_NO_COLON')
        elif re.match(r'(?i)^(epic|riot|account|steam)\s+(games?\s+)?(details|info)', line_s):
            line_types.append('SECTION_HEADER')
        elif line_s.startswith('\t') or line.startswith('\t'):
            line_types.append('TAB_INDENTED')
        elif re.match(r'^https?://', line_s):
            line_types.append('URL')
        elif '@' in line_s and ':' in line_s and not re.search(r'(?i)(login|pass|mail)', line_s):
            line_types.append('EMAIL_COLON_PASS')
        elif '@' in line_s:
            line_types.append('EMAIL_LINE')
        else:
            line_types.append('TEXT')

    return ' | '.join(line_types)


def check_parse_quality(record: dict) -> str:
    """Rate parse quality: OK, PARTIAL, EMPTY, ERROR."""
    parsed = record.get('parsed', {})
    if not parsed:
        return 'EMPTY'
    if parsed.get('_parse_error'):
        return 'ERROR'

    login = parsed.get('login', '')
    password = parsed.get('password', '')

    if not login:
        return 'NO_LOGIN'
    if not password:
        return 'NO_PASSWORD'

    # Check for suspicious values (newlines in fields, labels leaked into values)
    for field_name in ('login', 'password', 'email', 'email_password'):
        val = parsed.get(field_name, '')
        if '\n' in val:
            return 'NEWLINE_IN_FIELD'
        if re.search(r'(?i)^(mail|email|password|login|account)\s', val):
            return 'LABEL_IN_VALUE'

    return 'OK'


def analyze_file(filepath: str) -> dict:
    """Analyze a single credentials report file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        records = json.load(f)

    pattern_counter = Counter()
    quality_counter = Counter()
    problems = []

    for r in records:
        raw_text = r.get('raw_text', '')
        pattern = classify_pattern(raw_text)
        pattern_counter[pattern] += 1

        quality = check_parse_quality(r)
        quality_counter[quality] += 1

        if quality not in ('OK', 'EMPTY'):
            problems.append({
                'id': r.get('id'),
                'store_id': r.get('store_order_id') or r.get('store_listing_id'),
                'game': r.get('game', ''),
                'quality': quality,
                'pattern': pattern,
                'raw_text': raw_text[:300],
                'parsed': r.get('parsed', {}),
            })

    return {
        'total': len(records),
        'quality_summary': dict(quality_counter.most_common()),
        'pattern_counts': dict(pattern_counter.most_common(30)),
        'problems': problems[:100],  # cap at 100
    }


# ── Main ────────────────────────────────────────────────────────────
results = {}
report_files = [f for f in os.listdir(REPORT_DIR) if f.endswith('.json') and f != 'pattern_analysis.json']

for fname in sorted(report_files):
    filepath = os.path.join(REPORT_DIR, fname)
    print(f'Analyzing {fname}...')
    analysis = analyze_file(filepath)
    results[fname] = analysis
    print(f'  Total: {analysis["total"]}')
    print(f'  Quality: {analysis["quality_summary"]}')
    print(f'  Problems: {len(analysis["problems"])}')
    print(f'  Top patterns:')
    for pattern, count in list(analysis['pattern_counts'].items())[:10]:
        print(f'    {count:4d}x  {pattern}')

# Write full analysis
out_path = os.path.join(REPORT_DIR, 'pattern_analysis.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f'\nFull analysis: {out_path}')
