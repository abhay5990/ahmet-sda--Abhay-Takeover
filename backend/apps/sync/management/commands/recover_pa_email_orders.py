"""Run the bounded Gmail-backed PlayerAuctions order recovery worker."""

from django.core.management.base import BaseCommand

from apps.sync.services.playerauctions.email_recovery import (
    PlayerAuctionsEmailRecovery,
)


class Command(BaseCommand):
    help = 'Recover missing PlayerAuctions orders from Gmail notification emails.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        summary = PlayerAuctionsEmailRecovery().run(
            days=options['days'], limit=options['limit'],
        )
        self.stdout.write(self.style.SUCCESS(f'PA email recovery: {summary}'))
