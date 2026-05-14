"""Management command: find listings that were accidentally posted twice to the same store.

A duplicate is: the same OwnedProduct (same account) appearing in 2+ active listings
on the same integration_account. Having multiple listings for different accounts on the
same store/game combination is intentional and is NOT flagged.

Usage:
    python manage.py find_duplicate_listings
    python manage.py find_duplicate_listings --fix   # delete from marketplace, then mark DELETED
    python manage.py find_duplicate_listings --store <account_id>
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.integrations.proxy_pool import build_proxy_pool
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.services.dropship.delist import _delete_one_listing

_ACTIVE = [ListingStatus.LISTED, ListingStatus.PAUSED]


class Command(BaseCommand):
    help = 'Detect (and optionally remove) duplicate listings on the same store'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            default=False,
            help='Delete older duplicates from the marketplace, then mark DELETED locally',
        )
        parser.add_argument(
            '--store',
            type=int,
            default=None,
            metavar='ACCOUNT_ID',
            help='Limit scan to a specific IntegrationAccount id',
        )

    def handle(self, *args, **options):
        fix = options['fix']
        store_filter = options['store']

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== Duplicate Listing Scanner ===\n'
        ))

        proxy_pool = build_proxy_pool() if fix else None
        duplicates = self._find_by_owned_product(store_filter, fix, proxy_pool)

        if not duplicates:
            self.stdout.write(self.style.SUCCESS('No duplicates found.'))
        else:
            self.stdout.write(self.style.WARNING(
                f'\nTotal duplicate groups found: {len(duplicates)}'
            ))
            if not fix:
                self.stdout.write(
                    'Re-run with --fix to delete older duplicates from the marketplace.'
                )

    # ------------------------------------------------------------------

    def _delete_with_feedback(self, listings_to_delete: list[Listing], proxy_pool) -> None:
        for lst in listings_to_delete:
            ok = _delete_one_listing(lst, proxy_pool=proxy_pool)
            if ok:
                self.stdout.write(self.style.SUCCESS(
                    f'      -> Deleted from marketplace + marked DELETED: #{lst.id}'
                    f' (store_listing_id={lst.store_listing_id})'
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f'      -> FAILED to delete from marketplace: #{lst.id}'
                    f' (store_listing_id={lst.store_listing_id}) — skipped local update'
                ))

    # ------------------------------------------------------------------

    def _find_by_owned_product(self, store_filter, fix: bool, proxy_pool) -> list:
        """OwnedProduct linked to 2+ active listings on the same store."""
        qs = ListingOwnedProduct.objects.filter(
            listing__status__in=_ACTIVE,
        ).select_related(
            'listing__integration_account',
            'listing__integration_account__credential',
            'listing__game',
            'owned_product',
        )
        if store_filter:
            qs = qs.filter(listing__integration_account_id=store_filter)

        groups: dict[tuple, list] = defaultdict(list)
        for lop in qs:
            key = (lop.owned_product_id, lop.listing.integration_account_id)
            groups[key].append(lop)

        duplicates = {k: v for k, v in groups.items() if len(v) > 1}

        if not duplicates:
            return []

        self.stdout.write(self.style.WARNING(
            f'\n[Same OwnedProduct on same store] {len(duplicates)} group(s):\n'
        ))

        for (op_id, store_id), lops in duplicates.items():
            op = lops[0].owned_product
            store = lops[0].listing.integration_account
            self.stdout.write(
                f'  OwnedProduct #{op_id} ({op.login})  →  Store: {store.name} (#{store_id})'
            )
            listings_sorted = sorted(
                [lop.listing for lop in lops],
                key=lambda l: l.created_at,
            )
            for lst in listings_sorted:
                marker = '  [KEEP - newest]' if lst is listings_sorted[-1] else '  [DUPE - older]'
                self.stdout.write(
                    f'      Listing #{lst.id}  status={lst.status}'
                    f'  store_listing_id={lst.store_listing_id}'
                    f'  created={lst.created_at:%Y-%m-%d %H:%M}'
                    f'{marker}'
                )

            if fix:
                self._delete_with_feedback(listings_sorted[:-1], proxy_pool)

        return list(duplicates.keys())
