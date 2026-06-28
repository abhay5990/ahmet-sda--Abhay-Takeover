"""Backfill: mark ghost DropshipProducts as DELETED.

Ghost = status=LISTED but no remaining LISTED Listing attached.
These accumulated because bulk Listing.update(status=DELETED) in sync
services bypassed the listing_deactivated signal, leaving the
DropshipProduct in LISTED state. The resolver then blocked re-posting.

Safe because:
- SOLD DPs are untouched (handled by order signals).
- Items still available on source (LZT) will be re-fetched and re-posted
  once their DP status is DELETED (resolver only blocks LISTED+SOLD).
"""

from django.db import migrations
from django.utils import timezone


def backfill_ghost_dps(apps, schema_editor):
    DropshipProduct = apps.get_model('inventory', 'DropshipProduct')
    Listing = apps.get_model('listings', 'Listing')

    # All LISTED DP IDs
    listed_dp_ids = set(
        DropshipProduct.objects.filter(status='listed')
        .values_list('pk', flat=True)
    )
    if not listed_dp_ids:
        return

    # DP IDs that still have at least one LISTED listing
    active_dp_ids = set(
        Listing.objects.filter(
            dropship_product_id__in=listed_dp_ids,
            status='listed',
        ).values_list('dropship_product_id', flat=True)
    )

    ghost_dp_ids = listed_dp_ids - active_dp_ids
    if not ghost_dp_ids:
        return

    now = timezone.now()
    updated = DropshipProduct.objects.filter(pk__in=ghost_dp_ids).update(
        status='deleted',
        deleted_at=now,
    )
    print(f"\n  Backfill: marked {updated} ghost DropshipProduct(s) as DELETED")


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_remove_new_world_gameboost_mapping'),
        ('listings', '0001_initial'),  # Listing model dependency
    ]

    operations = [
        migrations.RunPython(
            backfill_ghost_dps,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
