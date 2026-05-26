"""Backfill sub_platform labels to slugs, rename to variant, add composite index.

Steps:
1. Backfill: convert old label values ("PlayStation", "Xbox", etc.) to canonical slugs
2. Rename column: sub_platform → variant
3. Add composite index for active count queries
"""

from django.db import migrations, models


LABEL_TO_SLUG = {
    "PlayStation": "psn",
    "Xbox": "xbox",
    "PC": "pc",
    "Android": "android",
    "iOS": "ios",
    "Switch": "switch",
    "PC - Legacy": "pc-legacy",
    "PC - Enhanced": "pc-enhanced",
    "PlayStation 4": "ps4",
    "PlayStation 5": "ps5",
    "Xbox One": "xbox-one",
    "Xbox Series X/S": "xbox-series",
}


def backfill_slugs(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    for old_label, slug in LABEL_TO_SLUG.items():
        Listing.objects.filter(sub_platform=old_label).update(sub_platform=slug)


def reverse_backfill(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    for old_label, slug in LABEL_TO_SLUG.items():
        Listing.objects.filter(variant=slug).update(variant=old_label)


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0002_add_admin_indexes"),
    ]

    operations = [
        # 1. Backfill labels → slugs (while column is still sub_platform)
        migrations.RunPython(backfill_slugs, reverse_backfill),
        # 2. Rename column
        migrations.RenameField(
            model_name="Listing",
            old_name="sub_platform",
            new_name="variant",
        ),
        # 3. Composite index for active count queries
        migrations.AddIndex(
            model_name="Listing",
            index=models.Index(
                fields=["integration_account", "game", "status", "variant"],
                name="listing_acct_game_status_var",
            ),
        ),
    ]
