"""Restore multi-account Eldorado offers that were incorrectly deleted.

Reads the original offer data from RawPayload, filters out sold credentials,
and re-creates the offer via the Eldorado API. On success, creates a new
Listing record and links the remaining OwnedProducts.

Usage:
    python manage.py restore_deleted_offers                  # dry-run (default)
    python manage.py restore_deleted_offers --execute        # actually create via API
    python manage.py restore_deleted_offers --listing 4863   # single listing only
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apis_sdk.clients.marketplaces.eldorado.mapper import EldoradoMapper
from apps.integrations.providers.registry import get_or_build_client
from apps.inventory.enums import OwnedProductStatus
from apps.inventory.models import OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
from apps.sync.enums import SyncLogLevel
from apps.sync.models import RawPayload
from apps.sync.services.cross_platform import _replace_listing_in_db
from apps.sync.services.shared.sync_log import log_sync, log_sync_error

logger = logging.getLogger(__name__)

# Listing IDs that need restoration (from damage report 2026-04-03).
DAMAGED_OFFERS: dict[int, str] = {
    8284: "6c03c1f4-a491-4648-f23e-08de7b84ddf6",
    4863: "a5c61c73-788c-4efb-370f-08de75d34c5c",
    3911: "254ff1e2-c97e-4a20-7ad4-08de80cf164a",
    5216: "a50005dd-e321-42a3-9e50-5bb6e2cb7430",
    3309: "91382226-314e-4ad4-a6f0-08de84e4dd1e",
    6998: "fea53599-2582-4b32-290e-08de8e288fae",
}

SOLD_STATUSES = (OwnedProductStatus.SOLD, OwnedProductStatus.MULTIPLE_SOLD)


def _find_sold_credential_ids(credential_entries: list[dict], sold_logins: set[str]) -> set:
    """Match sold logins to Eldorado credential entry IDs.

    Checks ALL 'key -> value' lines in secretDetails — handles
    'Epic Games ->', 'Steam ->', 'E-mail ->', etc.
    """
    exclude_ids: set = set()

    for entry in credential_entries:
        secret = entry.get("secretDetails", "")
        for line in secret.split("\n"):
            parts = line.split("->")
            if len(parts) >= 2:
                extracted = parts[1].strip().lower()
                if extracted in sold_logins:
                    exclude_ids.add(entry["id"])
                    break

    return exclude_ids


class Command(BaseCommand):
    help = (
        'Restore multi-account Eldorado offers that were deleted by '
        'stale_cleanup on 2026-04-03. Reads RawPayload, filters sold '
        'credentials, re-creates via API.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually create offers via API. Default is dry-run.',
        )
        parser.add_argument(
            '--listing',
            type=int,
            default=None,
            help='Restore a single listing by ID (e.g. --listing 4863).',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=2.0,
            help='Seconds between API calls (rate limit). Default: 2.0',
        )

    def handle(self, *args, **options):
        execute = options['execute']
        single_listing = options['listing']
        delay = options['delay']

        targets = self._resolve_targets(single_listing)
        if targets is None:
            return

        self.stdout.write(f'Processing {len(targets)} damaged offer(s)...')
        if not execute:
            self.stdout.write(self.style.WARNING('DRY RUN — add --execute to create offers.\n'))

        success, failed, skipped = 0, 0, 0
        target_keys = list(targets.keys())

        for listing_id, store_listing_id in targets.items():
            self._print_separator(listing_id, store_listing_id)

            try:
                result = self._process_one(listing_id, store_listing_id, execute=execute)
                if result == 'success':
                    success += 1
                elif result == 'skipped':
                    skipped += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f'  UNEXPECTED ERROR: {e}'))
                logger.exception('restore_deleted_offers: listing %s failed', listing_id)

            if execute and delay and listing_id != target_keys[-1]:
                self.stdout.write(f'  Waiting {delay}s (rate limit)...')
                time.sleep(delay)

        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Success: {success}, Skipped: {skipped}, Failed: {failed}'
        ))

    # ── Internals ──────────────────────────────────────────────────

    def _resolve_targets(self, single_listing: int | None) -> dict[int, str] | None:
        """Resolve which listings to process."""
        if single_listing is None:
            return DAMAGED_OFFERS

        if single_listing not in DAMAGED_OFFERS:
            self.stderr.write(self.style.ERROR(
                f'Listing {single_listing} is not in the damaged offers list.'
            ))
            return None

        return {single_listing: DAMAGED_OFFERS[single_listing]}

    def _print_separator(self, listing_id: int, store_listing_id: str) -> None:
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'Listing #{listing_id} | store_id={store_listing_id}')
        self.stdout.write(f'{"=" * 60}')

    def _process_one(self, listing_id: int, store_listing_id: str, *, execute: bool) -> str:
        """Process a single damaged offer. Returns 'success', 'skipped', or 'failed'."""

        # 1. Load listing + raw payload
        listing = self._load_listing(listing_id)
        if listing is None:
            return 'failed'

        account = listing.integration_account
        self.stdout.write(f'  Account: {account.slug} ({account.provider})')

        raw_data = self._load_raw_data(account, store_listing_id)
        if raw_data is None:
            return 'failed'

        # 2. Determine sold vs remaining OwnedProducts
        remaining, sold_logins = self._analyze_owned_products(listing)
        if remaining is None:
            return 'skipped'

        # 3. Build payload (excluding sold credentials)
        payload, cred_count = self._build_payload(raw_data, sold_logins)
        if payload is None:
            return 'skipped'

        self._print_payload_summary(payload, cred_count)

        if not execute:
            self.stdout.write(self.style.SUCCESS('  [DRY RUN] Would create offer with above payload.'))
            return 'success'

        # 4. Create via API
        new_offer, new_offer_id = self._create_offer(account, payload, listing_id)
        if new_offer is None:
            return 'failed'

        # 5. Update DB
        new_listing = _replace_listing_in_db(listing, new_offer_id, remaining, new_offer)

        # 6. Update OwnedProduct status: draft → listed
        OwnedProduct.objects.filter(
            id__in=[op.id for op in remaining],
            status=OwnedProductStatus.DRAFT,
        ).update(status=OwnedProductStatus.LISTED, updated_at=timezone.now())

        self.stdout.write(self.style.SUCCESS(
            f'  DB updated: new listing #{new_listing.id}, '
            f'{len(remaining)} OwnedProducts linked'
        ))

        log_sync(
            'offer_restore', SyncLogLevel.SUCCESS,
            f'Restored offer for listing #{listing_id} → new #{new_listing.id} '
            f'(offer_id={new_offer_id}, {cred_count} credentials)',
            listing=new_listing,
            integration_account=account,
        )

        return 'success'

    # ── Data loading ───────────────────────────────────────────────

    def _load_listing(self, listing_id: int) -> Listing | None:
        try:
            return Listing.objects.select_related(
                'integration_account__credential',
            ).get(id=listing_id)
        except Listing.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'  Listing #{listing_id} not found in DB.'))
            return None

    def _load_raw_data(self, account, store_listing_id: str) -> dict | None:
        try:
            raw_payload = RawPayload.objects.get(
                integration_account=account,
                resource_type='listings',
                remote_id=store_listing_id,
            )
            self.stdout.write(f'  RawPayload found (fetched_at={raw_payload.fetched_at})')
            return raw_payload.payload
        except RawPayload.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                f'  RawPayload not found for remote_id={store_listing_id}'
            ))
            return None

    # ── Analysis ───────────────────────────────────────────────────

    def _analyze_owned_products(self, listing: Listing) -> tuple[list | None, set[str]]:
        """Returns (remaining_products, sold_logins) or (None, _) if all sold."""
        lops = ListingOwnedProduct.objects.filter(
            listing=listing,
        ).select_related('owned_product')

        all_owned = {lop.owned_product for lop in lops}
        sold = {op for op in all_owned if op.status in SOLD_STATUSES}
        remaining = list(all_owned - sold)

        self.stdout.write(
            f'  OwnedProducts: total={len(all_owned)}, sold={len(sold)}, remaining={len(remaining)}'
        )

        if not remaining:
            self.stdout.write(self.style.WARNING('  All accounts sold — skipping.'))
            return None, set()

        sold_logins = {op.login.lower().strip() for op in sold if op.login}
        return remaining, sold_logins

    def _build_payload(self, raw_data: dict, sold_logins: set[str]) -> tuple[dict | None, int]:
        """Build create_offer payload excluding sold credentials."""
        credential_entries = raw_data.get("_credential_entries") or []
        exclude_ids = _find_sold_credential_ids(credential_entries, sold_logins)

        self.stdout.write(
            f'  Credential entries: total={len(credential_entries)}, excluding={len(exclude_ids)}'
        )

        payload = EldoradoMapper.build_from_raw(raw_data, exclude_credential_ids=exclude_ids)
        cred_count = len(payload.get("accountSecretDetails", []))

        if cred_count == 0:
            self.stderr.write(self.style.ERROR('  No credentials in payload — skipping.'))
            return None, 0

        return payload, cred_count

    # ── Output ─────────────────────────────────────────────────────

    def _print_payload_summary(self, payload: dict, cred_count: int) -> None:
        details = payload.get("details", {})
        pricing = details.get("pricing", {})
        game = payload.get("augmentedGame", {})

        self.stdout.write(f'  Title: {details.get("offerTitle", "")[:60]}')
        self.stdout.write(
            f'  Price: {pricing.get("pricePerUnit", {}).get("amount", "?")} '
            f'{pricing.get("pricePerUnit", {}).get("currency", "?")}'
        )
        self.stdout.write(f'  Game: {game.get("gameId", "?")} / {game.get("category", "?")}')
        self.stdout.write(f'  Credentials: {cred_count}')

    # ── API call ───────────────────────────────────────────────────

    def _create_offer(self, account, payload: dict, listing_id: int) -> tuple:
        """Create offer via Eldorado API. Returns (offer, offer_id) or (None, None)."""
        try:
            client = get_or_build_client(account.provider, account.credential)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'  Failed to build client: {e}'))
            return None, None

        self.stdout.write('  Calling create_offer...')
        result = client.create_offer(payload)

        if not result.ok:
            self.stderr.write(self.style.ERROR(f'  API error: {result.error}'))
            log_sync_error(
                'offer_restore',
                f'Failed to restore offer for listing #{listing_id}: {result.error}',
                integration_account=account,
            )
            return None, None

        new_offer = result.data
        new_offer_id = new_offer.id if new_offer else 'unknown'
        self.stdout.write(self.style.SUCCESS(f'  Offer created! New ID: {new_offer_id}'))
        return new_offer, new_offer_id
