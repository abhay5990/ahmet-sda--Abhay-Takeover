"""Management command: fix_r6_subplatforms

R6 instant listinglerinde platform mantığı düzeltmesi.

Eski mantık (yanlış): psn_connected → PlayStation seç
Yeni mantık (doğru):  psn_connected → PlayStation DOLU, seçme

Akış:
  1. R6 instant listingleri çek (listed/paused)
  2. ListingOwnedProduct → OwnedProduct → raw_data
  3. raw_data'dan uplay_psn_connected, uplay_xbox_connected oku
  4. Doğru sub_platform hesapla (PSN boş → PlayStation > Xbox boş → Xbox > PC)
  5. Mevcut sub_platform != doğru → düzelt

Kullanım:
  # Dry-run (sadece rapor)
  python manage.py fix_r6_subplatforms

  # Gerçekten çalıştır (relist dahil, 4 sn bekleme)
  python manage.py fix_r6_subplatforms --execute

  # Sadece DB güncelle, relist yapma
  python manage.py fix_r6_subplatforms --execute --no-relist

  # Bekleme süresini ayarla
  python manage.py fix_r6_subplatforms --execute --delay 6
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.posting.services.relist import relist_listing

# R6 game_id — proje genelinde sabit
R6_GAME_ID = 36

# Eldorado tradeEnvironmentId haritası
TRADE_ENV = {
    'PC':          ('0', 'PC'),
    'PlayStation': ('1', 'PlayStation'),
    'Xbox':        ('2', 'Xbox'),
}

# primary_linkable_platform mantığı: PlayStation > Xbox > PC
# PSN boşsa → PlayStation, Xbox boşsa → Xbox, ikisi de doluysa → PC
def _compute_correct_platform(psn_connected: bool, xbox_connected: bool) -> str:
    if not psn_connected:
        return 'PlayStation'
    if not xbox_connected:
        return 'Xbox'
    return 'PC'


def _extract_platform_flags(raw_data: dict) -> tuple[bool, bool] | None:
    """OwnedProduct.raw_data'dan psn/xbox connected bilgisini çek.

    raw_data iki formatta olabilir:
      - Doğrudan LZT payload (uplay_psn_connected üst seviyede)
      - Sarmalı format (raw_data.raw_data.uplay_psn_connected)

    Returns (psn_connected, xbox_connected) or None if no data.
    """
    if not isinstance(raw_data, dict):
        return None

    # raw_data doğrudan LZT payload ise
    psn = raw_data.get('uplay_psn_connected')
    xbox = raw_data.get('uplay_xbox_connected')

    # Sarmalı format: raw_data içinde raw_data
    if psn is None and xbox is None:
        inner = raw_data.get('raw_data')
        if isinstance(inner, dict):
            psn = inner.get('uplay_psn_connected')
            xbox = inner.get('uplay_xbox_connected')

    if psn is None and xbox is None:
        return None

    return bool(psn), bool(xbox)


def _build_mismatch_list():
    """R6 instant listinglerini tara, yanlış sub_platform olanları bul."""
    listings = (
        Listing.objects
        .filter(
            game_id=R6_GAME_ID,
            is_instant=True,
            status__in=[ListingStatus.LISTED, ListingStatus.PAUSED],
        )
        .select_related('integration_account', 'integration_account__credential')
    )

    mismatches = []
    skipped_no_product = 0
    skipped_no_flags = 0

    for listing in listings:
        # OwnedProduct bul
        link = (
            ListingOwnedProduct.objects
            .filter(listing=listing)
            .select_related('owned_product')
            .first()
        )
        if not link or not link.owned_product:
            skipped_no_product += 1
            continue

        product = link.owned_product
        flags = _extract_platform_flags(product.raw_data or {})
        if flags is None:
            skipped_no_flags += 1
            continue

        psn_connected, xbox_connected = flags
        correct_platform = _compute_correct_platform(psn_connected, xbox_connected)

        if listing.sub_platform == correct_platform:
            continue  # zaten doğru

        mismatches.append({
            'listing': listing,
            'product': product,
            'old_platform': listing.sub_platform,
            'new_platform': correct_platform,
            'psn_connected': psn_connected,
            'xbox_connected': xbox_connected,
        })

    return mismatches, skipped_no_product, skipped_no_flags


class Command(BaseCommand):
    help = 'R6 instant listinglerinde sub_platform mantığını düzeltir (ters platform bug fix)'

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
        execute = options['execute']
        no_relist = options['no_relist']
        delay = options['delay']

        self.stdout.write('R6 sub_platform mismatch taranıyor...\n')

        mismatches, skipped_no_product, skipped_no_flags = _build_mismatch_list()

        if skipped_no_product or skipped_no_flags:
            self.stdout.write(
                f'  Atlanan: {skipped_no_product} OwnedProduct yok, '
                f'{skipped_no_flags} platform bilgisi yok\n'
            )

        if not mismatches:
            self.stdout.write(self.style.SUCCESS('Düzeltilecek mismatch bulunamadı.'))
            return

        self.stdout.write(
            f"\n{'DRY-RUN' if not execute else 'EXECUTE'} — "
            f"{len(mismatches)} listing düzeltilecek\n"
            f"{'(relist YOK, sadece DB)' if no_relist else f'(relist VAR, {delay}s bekleme)'}\n"
            + '-' * 80
        )

        success_count = 0
        error_count = 0

        for item in mismatches:
            listing = item['listing']
            old_platform = item['old_platform']
            new_platform = item['new_platform']
            psn = item['psn_connected']
            xbox = item['xbox_connected']
            provider = listing.integration_account.provider if listing.integration_account else '?'

            self.stdout.write(
                f"  id={listing.id:<6} | {provider:<15} | "
                f"PSN={'Y' if psn else 'N'} Xbox={'Y' if xbox else 'N'} | "
                f"{old_platform:>12} → {new_platform:<12} | "
                f"status={listing.status}"
            )

            if not execute:
                continue

            # 1. raw_data içindeki tradeEnvironmentValues düzelt (Eldorado)
            raw = listing.raw_data or {}
            envs = raw.get('tradeEnvironmentValues') or []
            if envs:
                new_env_id, new_env_val = TRADE_ENV[new_platform]
                envs[0]['id'] = new_env_id
                envs[0]['value'] = new_env_val
                raw['tradeEnvironmentValues'] = envs
                listing.raw_data = raw

            # 2. DB sub_platform güncelle
            listing.sub_platform = new_platform
            listing.save(update_fields=['sub_platform', 'raw_data', 'updated_at'])

            if no_relist:
                self.stdout.write(self.style.WARNING('    DB güncellendi (relist atlandı)'))
                success_count += 1
                continue

            # 3. Relist
            result = relist_listing(listing)
            if result.ok:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'    Relist OK → yeni listing id={result.new_listing.id}'
                    )
                )
                success_count += 1
            else:
                self.stdout.write(
                    self.style.ERROR(f'    Relist HATA: {result.error}')
                )
                error_count += 1

            time.sleep(delay)

        self.stdout.write('-' * 80)
        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDRY-RUN bitti. {len(mismatches)} mismatch bulundu.\n'
                    'Gerçekten çalıştırmak için --execute ekle.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nİşlem tamamlandı. Başarılı: {success_count}, Hata: {error_count}'
                )
            )
