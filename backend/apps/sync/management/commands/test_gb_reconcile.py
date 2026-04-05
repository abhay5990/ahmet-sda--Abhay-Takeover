"""Test Gameboost non-legacy credential reconcile with real API call.

Simulates: 'ahmet' account sold on Eldorado, remove from Gameboost offer.

Usage:
    python manage.py test_gb_reconcile                # dry-run (default)
    python manage.py test_gb_reconcile --execute      # actually delete credential via API
"""

import logging

from django.core.management.base import BaseCommand

from apps.integrations.providers.registry import get_or_build_client
from apps.listings.models import Listing, ListingOwnedProduct
from apps.sync.models import RawPayload
from apps.sync.services.cross_platform import (
    _is_gameboost_legacy,
    _reconcile_gameboost_credentials,
)
from apps.sync.services.shared.credentials import parse_credentials_text

logger = logging.getLogger(__name__)

# Test parameters
TEST_OFFER_REMOTE_ID = '4373565'
TEST_SOLD_LOGIN = 'ahmet'


class Command(BaseCommand):
    help = 'Test Gameboost non-legacy credential reconcile (offer 4373565, sold=ahmet)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually delete credential via API. Default is dry-run.',
        )

    def handle(self, *args, **options):
        execute = options['execute']

        self.stdout.write('=== Gameboost Non-Legacy Reconcile Test ===\n')

        # 1. Load RawPayload
        try:
            rp = RawPayload.objects.get(
                integration_account__provider='gameboost',
                resource_type='listings',
                remote_id=TEST_OFFER_REMOTE_ID,
            )
        except RawPayload.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                f'RawPayload not found for remote_id={TEST_OFFER_REMOTE_ID}'
            ))
            return

        raw_data = rp.payload
        account = rp.integration_account
        self.stdout.write(f'Account: {account.slug}')
        self.stdout.write(f'Offer: {TEST_OFFER_REMOTE_ID}')

        # 2. Legacy check
        is_legacy = _is_gameboost_legacy(raw_data)
        self.stdout.write(f'Legacy: {is_legacy}')
        if is_legacy:
            self.stderr.write(self.style.ERROR('Offer is legacy! Cannot use credentials API.'))
            return

        # 3. Load listing + LP links
        try:
            listing = Listing.objects.get(
                integration_account=account,
                store_listing_id=TEST_OFFER_REMOTE_ID,
            )
        except Listing.DoesNotExist:
            self.stderr.write(self.style.ERROR('Listing not found in DB'))
            return

        lops = ListingOwnedProduct.objects.filter(
            listing=listing,
        ).select_related('owned_product')

        self.stdout.write(f'Listing #{listing.id} | status={listing.status} | LP links: {lops.count()}')
        for lop in lops:
            op = lop.owned_product
            self.stdout.write(f'  OwnedProduct #{op.id}: login={op.login} | status={op.status}')

        # 4. Find sold OwnedProduct
        sold_owned = None
        for lop in lops:
            if lop.owned_product.login and lop.owned_product.login.lower().strip() == TEST_SOLD_LOGIN:
                sold_owned = lop.owned_product
                break

        if not sold_owned:
            self.stderr.write(self.style.ERROR(
                f'OwnedProduct with login="{TEST_SOLD_LOGIN}" not found in listing links'
            ))
            return

        self.stdout.write(f'\nSold OwnedProduct: #{sold_owned.id} (login={sold_owned.login})')

        # 5. Credential matching preview
        entries = raw_data.get('_credential_entries', [])
        self.stdout.write(f'Credential entries: {len(entries)}')

        matched_id = None
        for entry in entries:
            cred_text = entry.get('credentials', '')
            if not cred_text:
                continue
            parsed = parse_credentials_text(cred_text)
            is_match = parsed.login and parsed.login.lower().strip() == TEST_SOLD_LOGIN
            status = 'MATCH' if is_match else 'skip'
            self.stdout.write(f'  entry_id={entry.get("id")} | login="{parsed.login}" | {status}')
            if is_match:
                matched_id = entry.get('id')

        if not matched_id:
            self.stderr.write(self.style.ERROR('No credential match found!'))
            return

        self.stdout.write(f'\nWill delete credential_id={matched_id} from offer {TEST_OFFER_REMOTE_ID}')

        if not execute:
            self.stdout.write(self.style.WARNING(
                '\nDRY RUN -- add --execute to actually call API'
            ))
            return

        # 6. Execute: build client and call _reconcile_gameboost_credentials
        self.stdout.write('\nExecuting real API call...')
        client = get_or_build_client(account.provider, account.credential)

        try:
            _reconcile_gameboost_credentials(
                listing=listing,
                sold_owned=sold_owned,
                account=account,
                client=client,
                raw_data=raw_data,
            )
            self.stdout.write(self.style.SUCCESS('\nSUCCESS! Credential deleted from Gameboost.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'\nFAILED: {e}'))
            return

        # 7. Verify DB state after
        remaining_lops = ListingOwnedProduct.objects.filter(listing=listing)
        self.stdout.write(f'\nPost-reconcile state:')
        self.stdout.write(f'  Listing #{listing.id}: status={listing.status}')
        self.stdout.write(f'  Remaining LP links: {remaining_lops.count()}')
        for lop in remaining_lops.select_related('owned_product'):
            self.stdout.write(f'    OwnedProduct #{lop.owned_product.id}: login={lop.owned_product.login}')
