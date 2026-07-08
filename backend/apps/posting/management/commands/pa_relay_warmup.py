"""
Management command: pa_relay_warmup

Pre-fetches PA tokens into the relay cache for all active PA integration accounts.
Call at startup (e.g. from gunicorn --on-starting hook or systemd ExecStartPost).

Usage:
    python manage.py pa_relay_warmup
    python manage.py pa_relay_warmup --force   # bypass relay cache
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Pre-warm PA relay token cache for all active PA integration accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='Force relay to bypass cache and perform fresh browser login.',
        )

    def handle(self, *args, **options):
        force = options['force']

        try:
            from apps.integrations.models import IntegrationAccount
            from apis_sdk.clients.services.pa_relay import PaRelayClient, PaRelayConfig
            from apis_sdk.infrastructure.http.requests_transport import RequestsTransport
        except ImportError as e:
            self.stderr.write(f"Import error: {e}")
            return

        pa_accounts = IntegrationAccount.objects.filter(
            provider='playerauctions',
            is_active=True,
        ).select_related('credential')

        if not pa_accounts.exists():
            self.stdout.write("No active PA accounts found — skipping warmup.")
            return

        stores = []
        for acc in pa_accounts:
            try:
                creds = acc.credential.credentials
                username = creds.get('username', '')
                password = creds.get('password', '')
                store_slug = creds.get('store_slug', '') or acc.slug or username
                relay_url = creds.get('relay_url', 'http://35.231.166.148:3001')
                relay_secret = creds.get('relay_secret', 'pa-relay-secret-2026')

                if not username or not password:
                    self.stdout.write(f"  Skipping {acc.name} — no username/password")
                    continue

                stores.append({
                    'store': store_slug,
                    'username': username,
                    'password': password,
                    '_relay_url': relay_url,
                    '_relay_secret': relay_secret,
                })
                self.stdout.write(f"  Queued: {acc.name} → store={store_slug}")
            except Exception as e:
                self.stdout.write(f"  Error reading {acc.name}: {e}")

        if not stores:
            self.stdout.write("No stores to warm up.")
            return

        # Group by relay URL (in case different accounts use different relays)
        relay_url = stores[0]['_relay_url']
        relay_secret = stores[0]['_relay_secret']
        warmup_payload = [
            {'store': s['store'], 'username': s['username'], 'password': s['password']}
            for s in stores
        ]

        try:
            transport = RequestsTransport()
            relay = PaRelayClient(
                config=PaRelayConfig(base_url=relay_url, relay_secret=relay_secret),
                transport=transport,
            )
            ok = relay.warmup(warmup_payload, force_refresh=force)
            if ok:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"PA relay warmup accepted for {len(warmup_payload)} store(s) "
                        f"(force={force})"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING("PA relay warmup request failed — check relay logs")
                )
        except Exception as e:
            self.stderr.write(f"PA relay warmup error: {e}")
