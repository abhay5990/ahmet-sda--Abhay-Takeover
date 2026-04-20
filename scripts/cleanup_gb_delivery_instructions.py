"""Cleanup Gameboost delivery_instructions: remove credentials, set standard message.

For all draft + listed offers:
1. Parse credentials from delivery_instructions
2. If offer's credentials.login/password is empty -> fill from parsed data
3. Replace delivery_instructions with a standard message
4. Log all failures and unparseable offers

Usage (from project root):
    python scripts/cleanup_gb_delivery_instructions.py --dry-run     # analyze only, write JSON report
    python scripts/cleanup_gb_delivery_instructions.py --apply        # actually update offers
    python scripts/cleanup_gb_delivery_instructions.py --apply --resume-from 150  # resume from page 150
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

# -- Bootstrap Django --------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

from apps.integrations.models import IntegrationAccount  # noqa: E402
from apps.integrations.providers.registry import get_or_build_client  # noqa: E402
from apps.sync.services.shared.credentials import parse_credentials_text  # noqa: E402

# -- Config ------------------------------------------------------------------
ACCOUNT_SLUG = 'gameboost-store4gamers'
PER_PAGE = 50  # Gameboost API max per_page is 50
DELAY = 0.15  # seconds between API calls (retry policy handles 429)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'gb_delivery_cleanup')

STANDARD_MESSAGE = (
    "Thank you for your purchase! "
    "If you need any help with the account, please contact me first "
    "before opening a dispute. I'm happy to assist!"
)

# Email provider mapping: domain keywords -> provider value for Gameboost
# Checked via DI parse email_login_link data (2026-04-09)
_EMAIL_PROVIDER_MAP = {
    # Rambler family
    'rambler.ru': 'mail.rambler.ru',
    'myrambler.ru': 'mail.rambler.ru',
    'autorambler.ru': 'mail.rambler.ru',
    # Microsoft family
    'outlook.com': 'outlook.com',
    'hotmail.com': 'outlook.com',
    'live.com': 'outlook.com',
    # Google
    'gmail.com': 'gmail.com',
    # zsthost
    'jubilantmail.icu': 'mail.zsthost.com',
    'mellifluousmail.icu': 'mail.zsthost.com',
    'synergymail.xyz': 'mail.zsthost.com',
}

# Domain suffixes/patterns that map to firstmail.ltd or notletters.com
# These are custom domains hosted on those platforms
_NOTLETTERS_DOMAINS = {
    'antoninusmail.com', 'arborolatrymail.ru', 'barnburnermail.ru',
    'belettersmail.com', 'chrysothamnusmail.com', 'closuremail.com',
    'dermocertlmail.com', 'dictatemail.com', 'dropkickmail.com',
    'folderolmail.ru', 'geoffroeamail.com', 'lettersboxmail.com',
    'muraomail.com', 'nolettersbox.com', 'notboxletters.com',
    'notlettersmail.com', 'occupancymail.com', 'plottermail.com',
    'suffragettemail.com', 'tendernessmail.ru', 'thrombosismail.com',
    'tiebreakermail.ru', 'vertebratemail.ru',
}


def detect_email_provider(email: str) -> str:
    """Detect email provider from email address domain.

    Returns provider string or empty string if unknown.
    """
    if not email or '@' not in email:
        return ''

    domain = email.split('@')[1].lower()

    # Direct match
    if domain in _EMAIL_PROVIDER_MAP:
        return _EMAIL_PROVIDER_MAP[domain]

    # Known notletters domains
    if domain in _NOTLETTERS_DOMAINS:
        return 'notletters.com/email/login'

    # Default: most custom domains are firstmail.ltd hosted
    # Only apply if domain doesn't look like a major provider
    major = {'gmail.com', 'yahoo.com', 'icloud.com', 'protonmail.com', 'proton.me',
             'yandex.ru', 'yandex.com', 'mail.ru', 'aol.com'}
    if domain not in major:
        return 'firstmail.ltd/webmail'

    return ''


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_all_offers(facade, statuses):
    """Fetch all offers for given statuses, paginated."""
    all_offers = []
    for status in statuses:
        page = 1
        while True:
            result = facade.list_offers(params={
                'filter[status]': status,
                'per_page': PER_PAGE,
                'page': page,
            })
            if not result.ok:
                print(f"  ERROR fetching {status} page {page}: {result.error.message}")
                break

            offers = result.data
            all_offers.extend(offers)

            # Pagination info
            pagination = (result.meta or {}).get('pagination', {})
            last_page = pagination.get('last_page', 1)
            total = pagination.get('total', 0)

            if page == 1:
                print(f"  {status}: {total} offers, {last_page} pages")

            if page >= last_page:
                break
            page += 1
            time.sleep(DELAY)

    return all_offers


def analyze_offer(offer):
    """Analyze a single offer. Returns a dict with analysis results."""
    offer_id = offer.id
    creds = offer.credentials
    di = offer.delivery_instructions or ''

    has_di = bool(di.strip())
    login_empty = not creds or not creds.login
    password_empty = not creds or not creds.password

    # Already standard message?
    if di.strip() == STANDARD_MESSAGE:
        return {
            'offer_id': offer_id,
            'status': offer.status,
            'action': 'skip_already_clean',
            'has_di': False,
            'di_preview': '',
        }

    # No delivery instructions
    if not has_di:
        return {
            'offer_id': offer_id,
            'status': offer.status,
            'action': 'skip_empty_di',
            'has_di': False,
            'di_preview': '',
        }

    # Parse credentials from delivery_instructions
    parsed = parse_credentials_text(di)
    parsed_dict = asdict(parsed)
    has_parsed_login = bool(parsed.login)
    has_parsed_password = bool(parsed.password)

    # Determine action — only fill creds on instant delivery offers
    is_manual = offer.is_manual_delivery
    needs_cred_fill = (
        not is_manual
        and (login_empty or password_empty)
        and (has_parsed_login or has_parsed_password)
    )

    # Detect email_provider if empty
    provider_empty = not creds or not creds.email_provider
    detected_provider = ''
    if provider_empty:
        # Try from email_login first, then login
        email_for_detect = (creds.email_login if creds else None) or ''
        if '@' not in email_for_detect:
            email_for_detect = (creds.login if creds else None) or ''
        detected_provider = detect_email_provider(email_for_detect)

    return {
        'offer_id': offer_id,
        'status': offer.status,
        'title': offer.title[:80],
        'is_manual': is_manual,
        'action': 'update',
        'has_di': True,
        'di_original': di,
        'di_preview': di[:200],
        'current_creds': {
            'login': creds.login if creds else None,
            'password': creds.password if creds else None,
            'email_login': creds.email_login if creds else None,
            'email_password': creds.email_password if creds else None,
            'email_provider': creds.email_provider if creds else None,
        },
        'parsed_from_di': parsed_dict,
        'needs_cred_fill': needs_cred_fill,
        'login_empty': login_empty,
        'password_empty': password_empty,
        'provider_empty': provider_empty,
        'detected_provider': detected_provider,
    }


def build_update_payload(analysis):
    """Build PATCH payload from analysis.

    Updates delivery_instructions + email_provider (if empty and detected).
    Credentials (login/password) are NOT touched.
    """
    payload = {
        'delivery_instructions': STANDARD_MESSAGE,
    }

    # Fill email_provider if detected
    detected = analysis.get('detected_provider', '')
    if analysis.get('provider_empty') and detected:
        payload['email_provider'] = detected

    return payload


def run_dry_run(facade):
    """Fetch all offers, analyze, write report."""
    ensure_output_dir()

    print("Fetching all draft + listed offers...")
    offers = fetch_all_offers(facade, ['listed', 'draft'])
    print(f"\nTotal offers fetched: {len(offers)}")

    results = []
    skipped = 0
    to_update = 0
    needs_cred_fill = 0
    provider_fill = 0
    empty_di = 0
    already_clean = 0

    for offer in offers:
        analysis = analyze_offer(offer)
        results.append(analysis)

        action = analysis['action']
        if action == 'skip_empty_di':
            empty_di += 1
            skipped += 1
        elif action == 'skip_already_clean':
            already_clean += 1
            skipped += 1
        elif action == 'update':
            to_update += 1
            if analysis.get('needs_cred_fill'):
                needs_cred_fill += 1
            if analysis.get('provider_empty') and analysis.get('detected_provider'):
                provider_fill += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"  DRY-RUN SUMMARY")
    print(f"{'='*60}")
    print(f"  Total offers:        {len(offers)}")
    print(f"  Already clean:       {already_clean}")
    print(f"  Empty DI:            {empty_di}")
    print(f"  To update:           {to_update}")
    print(f"  - Needs cred fill:   {needs_cred_fill}")
    print(f"  - Provider fill:     {provider_fill}")
    print(f"  - DI only:           {to_update - needs_cred_fill}")

    # Write detailed report
    report_path = os.path.join(OUTPUT_DIR, 'dry_run_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Report written to: {report_path}")

    # Write offers needing cred fill (for manual review)
    cred_fill_items = [r for r in results if r.get('needs_cred_fill')]
    if cred_fill_items:
        cred_path = os.path.join(OUTPUT_DIR, 'needs_cred_fill.json')
        with open(cred_path, 'w', encoding='utf-8') as f:
            json.dump(cred_fill_items, f, indent=2, ensure_ascii=False, default=str)
        print(f"  Cred fill report:  {cred_path}")

    # Write unparseable (has DI but parse yielded no login)
    unparseable = [
        r for r in results
        if r['action'] == 'update'
        and not r['parsed_from_di'].get('login')
        and not r['parsed_from_di'].get('password')
    ]
    if unparseable:
        unp_path = os.path.join(OUTPUT_DIR, 'unparseable.json')
        with open(unp_path, 'w', encoding='utf-8') as f:
            json.dump(unparseable, f, indent=2, ensure_ascii=False, default=str)
        print(f"  Unparseable:       {unp_path} ({len(unparseable)} offers)")


def run_apply(facade, resume_from_page=1):
    """Fetch all offers, update delivery_instructions."""
    ensure_output_dir()

    print("Fetching all draft + listed offers...")
    offers = fetch_all_offers(facade, ['listed', 'draft'])
    print(f"\nTotal offers fetched: {len(offers)}")

    updated = 0
    failed = 0
    skipped = 0
    failures = []

    for i, offer in enumerate(offers):
        analysis = analyze_offer(offer)

        if analysis['action'] != 'update':
            skipped += 1
            continue

        payload = build_update_payload(analysis)

        # Update
        result = facade.update_offer(str(offer.id), payload)

        if result.ok:
            updated += 1
            provider_note = f" [+provider={payload.get('email_provider', '')}]" if 'email_provider' in payload else ""
            if updated % 100 == 0 or updated <= 3:
                print(f"  [{updated}] offer {offer.id} updated{provider_note}")
        else:
            failed += 1
            failure_record = {
                'offer_id': offer.id,
                'status': offer.status,
                'error': str(result.error.message) if result.error else 'unknown',
                'error_category': str(result.error.category) if result.error else 'unknown',
                'di_original': analysis.get('di_original', ''),
                'payload': payload,
            }
            failures.append(failure_record)
            print(f"  FAIL offer {offer.id}: {result.error.message if result.error else 'unknown'}")

        time.sleep(DELAY)

    # Summary
    print(f"\n{'='*60}")
    print(f"  APPLY SUMMARY")
    print(f"{'='*60}")
    print(f"  Total offers:  {len(offers)}")
    print(f"  Updated:       {updated}")
    print(f"  Failed:        {failed}")
    print(f"  Skipped:       {skipped}")

    # Write failures
    if failures:
        fail_path = os.path.join(OUTPUT_DIR, 'update_failures.json')
        with open(fail_path, 'w', encoding='utf-8') as f:
            json.dump(failures, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Failures written to: {fail_path}")
        print(f"  REVIEW THESE — {failed} offers were not updated!")
    else:
        print(f"\n  All offers updated successfully!")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='Analyze only, write JSON report')
    mode.add_argument('--apply', action='store_true', help='Actually update offers')
    parser.add_argument('--resume-from', type=int, default=1,
                        help='Resume from page N (for --apply)')
    args = parser.parse_args()

    # Build client
    account = IntegrationAccount.objects.select_related('credential').get(
        slug=ACCOUNT_SLUG, is_active=True,
    )
    if not hasattr(account, 'credential') or not account.credential.is_active:
        sys.exit(f'ERROR: {ACCOUNT_SLUG} has no active credentials')

    facade = get_or_build_client('gameboost', account.credential)
    print(f'Client built for: {ACCOUNT_SLUG}\n')

    if args.dry_run:
        run_dry_run(facade)
    elif args.apply:
        run_apply(facade, resume_from_page=args.resume_from)


if __name__ == '__main__':
    main()
