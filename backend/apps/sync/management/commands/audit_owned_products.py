"""Audit OwnedProduct table for bad/suspicious login values.

Usage:
    python manage.py audit_owned_products          # sadece raporla
    python manage.py audit_owned_products --delete  # bozuklari sil
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from apps.inventory.models import OwnedProduct


# Known bad patterns: labels that should never be a login
_KNOWN_BAD_LOGINS = {
    'PSN ID', 'Xbox ID', 'epic', 'Login', 'Epic mail', 'Mail Adress',
    'riot', 'PSN Username', 'PSN ID and mail', 'Account Mail',
    'rockstar ID', 'Xbox Username', 'Thanks for purchase.',
    'https', 'account', 'steam', 'ubi', 'Ubisoft Username',
    'SN Username', 'Secuirty Mail Pass', 'worldrecord pass',
    'Epic Games ->', 'mail domain',
}


class Command(BaseCommand):
    help = 'Audit OwnedProduct logins for parser bugs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete', action='store_true',
            help='Delete bad records instead of just reporting',
        )

    def handle(self, *args, **options):
        delete = options['delete']

        total = OwnedProduct.objects.count()
        self.stdout.write(f'\nToplam OwnedProduct: {total}\n')

        # 1. Known bad logins (exact match)
        q_known = Q()
        for bl in _KNOWN_BAD_LOGINS:
            q_known |= Q(login=bl)
        known_bad = OwnedProduct.objects.filter(q_known)
        known_count = known_bad.count()

        # 2. Multi-word logins (space in login)
        multi_word = OwnedProduct.objects.filter(login__contains=' ')
        multi_count = multi_word.count()

        # 3. Duplicate logins (same login, multiple records)
        dupes = (
            OwnedProduct.objects
            .values('login')
            .annotate(cnt=Count('id'))
            .filter(cnt__gt=1)
            .order_by('-cnt')
        )
        dupe_login_count = dupes.count()
        dupe_total = sum(d['cnt'] for d in dupes)

        # Report
        self.stdout.write(self.style.WARNING('=== AUDIT SONUCLARI ===\n'))

        # Known bad
        if known_count:
            self.stdout.write(self.style.ERROR(
                f'[HATA] Bilinen bozuk login: {known_count} kayit'
            ))
            by_login = (
                known_bad.values('login')
                .annotate(cnt=Count('id'))
                .order_by('-cnt')
            )
            for row in by_login:
                self.stdout.write(f"  {row['cnt']:4d}  {row['login']}")
        else:
            self.stdout.write(self.style.SUCCESS(
                '[OK] Bilinen bozuk login yok'
            ))

        self.stdout.write('')

        # Multi-word
        if multi_count:
            self.stdout.write(self.style.ERROR(
                f'[HATA] Bosluklu login: {multi_count} kayit'
            ))
            for item in multi_word[:20]:
                self.stdout.write(
                    f'  id={item.id}  login={item.login!r:.50}'
                )
            if multi_count > 20:
                self.stdout.write(f'  ... ve {multi_count - 20} daha')
        else:
            self.stdout.write(self.style.SUCCESS(
                '[OK] Bosluklu login yok'
            ))

        self.stdout.write('')

        # Duplicates summary
        self.stdout.write(
            f'[INFO] Duplicate login: {dupe_login_count} login, '
            f'{dupe_total} toplam kayit'
        )
        for d in list(dupes)[:10]:
            self.stdout.write(f"  {d['cnt']:4d}  {d['login']}")

        self.stdout.write('')

        # Delete if requested
        bad_qs = OwnedProduct.objects.filter(q_known | Q(login__contains=' '))
        bad_total = bad_qs.count()

        if bad_total == 0:
            self.stdout.write(self.style.SUCCESS(
                'Silinecek bozuk kayit yok - tablo temiz!'
            ))
            return

        if delete:
            deleted = bad_qs.delete()
            self.stdout.write(self.style.SUCCESS(
                f'Silindi: {deleted[0]} kayit ({deleted[1]})'
            ))
            self.stdout.write(
                f'Kalan OwnedProduct: {OwnedProduct.objects.count()}'
            )
        else:
            self.stdout.write(self.style.WARNING(
                f'{bad_total} bozuk kayit bulundu. '
                f'Silmek icin: python manage.py audit_owned_products --delete'
            ))
