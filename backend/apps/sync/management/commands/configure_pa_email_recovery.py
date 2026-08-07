"""Store the common Gmail IMAP recovery mailbox in encrypted SDA credentials."""

import sys

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import ServiceCredential, ServiceType
from apps.sync.services.playerauctions.email_recovery import IMAP_CREDENTIAL_SLUG


DEFAULT_RECIPIENT_MAP = {
    'csgosmurfkings@gmail.com': 'playerauctions-csgosmurfkings',
    'abhishekdilipjain@gmail.com': 'playerauctions-vapenation234',
}


class Command(BaseCommand):
    help = 'Configure the encrypted common Gmail mailbox for PA order recovery.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument(
            '--app-password-stdin', action='store_true',
            help='Read the Gmail app password from standard input only.',
        )

    def handle(self, *args, **options):
        if not options['app_password_stdin']:
            raise CommandError('Use --app-password-stdin; never pass secrets as CLI arguments.')
        app_password = sys.stdin.readline().strip()
        if not app_password:
            raise CommandError('No IMAP app password was supplied on standard input.')

        ServiceCredential.objects.update_or_create(
            slug=IMAP_CREDENTIAL_SLUG,
            defaults={
                'name': 'PlayerAuctions Gmail Recovery',
                'service_type': ServiceType.OTHER,
                'credentials': {
                    'email': options['email'].strip().lower(),
                    'app_password': app_password,
                    'host': 'imap.gmail.com',
                    'port': 993,
                    'recipient_map': DEFAULT_RECIPIENT_MAP,
                },
                'is_active': True,
                'notes': 'Secondary PA order-recovery trigger; authoritative order data remains relay-fetched.',
            },
        )
        self.stdout.write(self.style.SUCCESS('PA Gmail recovery credential configured.'))
