"""Management command: fix_fortnite_subplatforms

Fortnite instant listinglerinde başlıktaki platform tag'i ([PC/PSN] gibi)
ile DB'deki sub_platform alanını karşılaştırır; uyumsuzluk varsa:
  1. sub_platform'u title'dan türetilen doğru değere günceller
  2. raw_data['tradeEnvironmentValues'] içindeki id/value'yu düzeltir
  3. relist_listing() ile marketplace'de eski ilanı silip doğru kategoride
     yeniden oluşturur

Kullanım:
  # Neyi düzelteceğini göster (dry-run, API çağrısı yok)
  python manage.py fix_fortnite_subplatforms

  # Gerçekten çalıştır (relist dahil, her listing arasında 4 sn bekleme)
  python manage.py fix_fortnite_subplatforms --execute

  # Sadece DB + raw_data güncelle, relist yapma
  python manage.py fix_fortnite_subplatforms --execute --no-relist

  # Bekleme süresini ayarla
  python manage.py fix_fortnite_subplatforms --execute --delay 6
"""

from __future__ import annotations

import re
import time

from django.core.management.base import BaseCommand

from apps.listings.models import Listing
from apps.posting.services.relist import relist_listing

# Eldorado tradeEnvironmentId haritası
TRADE_ENV = {
    'PC':          ('0', 'PC'),
    'PlayStation': ('1', 'PlayStation'),
    'Xbox':        ('2', 'Xbox'),
}

# Sadece bu sub_platform değerlerindeki yanlışları düzeltiyoruz
TARGET_PLATFORMS = {'PlayStation', 'Xbox'}

# Her sub_platform için title'da olması gereken tag'ler
PLATFORM_TAGS = {
    'PlayStation': {'PSN'},
    'Xbox':        {'XBOX', 'XBL'},
}


def _is_mismatch(sub_platform: str, title_parts: list[str]) -> bool:
    """sub_platform için beklenen tag'lerden hiçbiri title'da yoksa mismatch."""
    expected = PLATFORM_TAGS.get(sub_platform, set())
    return not any(tag in title_parts for tag in expected)


def _derive_correct_platform(title_parts: list[str]) -> str:
    """title_parts'tan doğru sub_platform değerini türet."""
    if 'PSN' in title_parts:
        return 'PlayStation'
    if 'XBOX' in title_parts or 'XBL' in title_parts:
        return 'Xbox'
    return 'PC'


def _build_mismatch_list():
    qs = Listing.objects.filter(
        game_id=36,
        is_instant=True,
        status__in=['listed', 'paused'],
        sub_platform__in=list(TARGET_PLATFORMS),
    ).select_related('integration_account', 'integration_account__credential')

    mismatches = []
    for listing in qs:
        title_upper = listing.title.upper()
        m = re.search(r'\[([A-Z/]+)\]', title_upper)
        if not m:
            continue

        title_tag   = m.group(1)
        title_parts = title_tag.split('/')

        if not _is_mismatch(listing.sub_platform, title_parts):
            continue  # zaten doğru

        mismatches.append({
            'listing':      listing,
            'old_platform': listing.sub_platform,
            'new_platform': _derive_correct_platform(title_parts),
            'title_tag':    title_tag,
        })

    return mismatches


class Command(BaseCommand):
    help = 'Fortnite instant listinglerinde sub_platform / tradeEnvironment uyumsuzluklarını düzeltir ve relist yapar'

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            default=False,
            help='Gerçekten değişiklik yap (varsayılan: dry-run)',
        )
        parser.add_argument(
            '--no-relist',
            action='store_true',
            default=False,
            help='Sadece DB + raw_data güncelle, relist yapma',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=4.0,
            help='Her relist arasında kaç saniye bekle (varsayılan: 4)',
        )

    def handle(self, *args, **options):
        execute   = options['execute']
        no_relist = options['no_relist']
        delay     = options['delay']

        mismatches = _build_mismatch_list()

        if not mismatches:
            self.stdout.write(self.style.SUCCESS('Düzeltilecek mismatch bulunamadı.'))
            return

        self.stdout.write(
            f"\n{'DRY-RUN' if not execute else 'EXECUTE'} — "
            f"{len(mismatches)} listing düzeltilecek\n"
            f"{'(relist YOK, sadece DB)' if no_relist else f'(relist VAR, {delay}s bekleme)'}\n"
            + '-' * 70
        )

        for item in mismatches:
            listing      = item['listing']
            old_platform = item['old_platform']
            new_platform = item['new_platform']
            title_tag    = item['title_tag']
            new_env_id, new_env_val = TRADE_ENV[new_platform]

            self.stdout.write(
                f"  id={listing.id:<6} | [{title_tag}] | "
                f"{old_platform} → {new_platform} | status={listing.status}"
            )

            if not execute:
                continue

            # 1. raw_data içindeki tradeEnvironmentValues'u düzelt
            raw = listing.raw_data or {}
            envs = raw.get('tradeEnvironmentValues') or []
            if envs:
                envs[0]['id']    = new_env_id
                envs[0]['value'] = new_env_val
                raw['tradeEnvironmentValues'] = envs
                listing.raw_data = raw

            # 2. DB sub_platform güncelle
            listing.sub_platform = new_platform
            listing.save(update_fields=['sub_platform', 'raw_data', 'updated_at'])

            if no_relist:
                self.stdout.write(self.style.WARNING('    DB güncellendi (relist atlandı)'))
                continue

            # 3. Relist
            result = relist_listing(listing)
            if result.ok:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'    Relist OK → yeni listing id={result.new_listing.id}'
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'    Relist HATA: {result.error}')
                )

            time.sleep(delay)

        self.stdout.write('-' * 70)
        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    '\nDRY-RUN bitti. Gerçekten çalıştırmak için --execute ekle.'
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS('\nİşlem tamamlandı.'))
