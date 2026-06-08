"""Quick test: fetch the last 50 PlayerAuctions listings for an account.

This is a read-only smoke test for the PlayerAuctions SDK + IntegrationAccount
wiring. It builds the client the same way the sync chain does
(``get_or_build_client`` + proxy pool) and prints one page of offers.

Usage:
    python manage.py test_pa_listings <account-slug>
    python manage.py test_pa_listings playerauctions-store4gamers --status Active

If no slug is given, the first active PlayerAuctions account is used.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name

PROVIDER = 'playerauctions'


class Command(BaseCommand):
    help = 'Fetch the last 50 PlayerAuctions listings (read-only smoke test).'

    def add_arguments(self, parser):
        parser.add_argument(
            'account',
            nargs='?',
            default=None,
            help='IntegrationAccount slug. Defaults to first active PA account.',
        )
        parser.add_argument(
            '--status',
            default='',
            help="Listing status filter (e.g. 'Active', 'Hidden'). Empty = all.",
        )
        parser.add_argument(
            '--page-size',
            type=int,
            default=50,
            help='Number of listings to fetch (default 50).',
        )

    def handle(self, *args, **options):
        slug = options['account']
        status = options['status']
        page_size = options['page_size']

        # 1. Resolve account
        qs = IntegrationAccount.objects.select_related('credential', 'group').filter(
            provider=PROVIDER, is_active=True,
        )
        if slug:
            qs = qs.filter(slug=slug)
        account = qs.first()
        if account is None:
            raise CommandError(
                f'No active PlayerAuctions account found'
                + (f' with slug "{slug}".' if slug else '.')
            )
        if not hasattr(account, 'credential') or not account.credential.is_active:
            raise CommandError(f'Account "{account.slug}" has no active credentials.')

        self.stdout.write(f'Account: {account.name} ({account.slug})')

        # 2. Build client exactly like the sync chain does
        proxy_pool = build_proxy_pool()
        proxy_group = get_group_name(account)
        client = get_or_build_client(
            PROVIDER,
            account.credential,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
        )
        if proxy_pool and proxy_group:
            count = len(proxy_pool.get_all(group=proxy_group))
            self.stdout.write(f'Proxy: group={proxy_group} ({count} proxies)')
        else:
            self.stdout.write(self.style.WARNING('Proxy: none — direct IP'))

        # 3. Fetch one page (page 1) of listings
        self.stdout.write(
            f'Fetching page 1 (page_size={page_size}, status={status or "all"})...'
        )
        result = client.list_offers(
            page=1,
            page_size=page_size,
            listing_status=status,
            proxy_group=proxy_group,
        )

        # 4. Report
        if not result.ok:
            msg = result.error.message if result.error else 'unknown error'
            raise CommandError(f'PlayerAuctions API error: {msg}')

        offers = result.data or []
        self.stdout.write(self.style.SUCCESS(f'Got {len(offers)} listings:'))
        for i, offer in enumerate(offers, 1):
            self.stdout.write(
                f'{i:>3}. [{offer.offer_id}] {offer.title} '
                f'— {offer.total_price} ({offer.system_status}) '
                f'exp={offer.expired_time_string}'
            )

        pagination = result.meta.get('pagination', {}) if result.meta else {}
        if pagination:
            self.stdout.write(
                f"\nPage {pagination.get('current_page')}/"
                f"{pagination.get('total_pages')} "
                f"— total {pagination.get('total_count')} listings"
            )
