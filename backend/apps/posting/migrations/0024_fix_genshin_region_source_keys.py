"""Populate source_key for Genshin Impact region variants.

The original seed (0010) left source_key blank, causing variant_context
keys to fall back to slugs (na/eu/asia/tw).  The LZT source sends
region as "America"/"Europe"/"Asia"/"TW,HK,MO" which doesn't match
the slugs — breaking Eldorado trade-environment resolution.

This migration sets source_key to the raw mihoyo_region values so the
case-insensitive lookup in get_external_id() can match them.
"""

from django.db import migrations


GAME_SLUG = "genshin-impact"

# (variant_slug, source_key_to_set)
SOURCE_KEYS = [
    ("na", "America"),
    ("eu", "Europe"),
    ("asia", "Asia"),
    ("tw", "TW,HK,MO"),
]


def forwards(apps, schema_editor):
    GameVariant = apps.get_model("posting", "GameVariant")
    for slug, source_key in SOURCE_KEYS:
        GameVariant.objects.filter(
            game__slug=GAME_SLUG,
            type="region",
            slug=slug,
        ).update(source_key=source_key)


def backwards(apps, schema_editor):
    GameVariant = apps.get_model("posting", "GameVariant")
    for slug, _ in SOURCE_KEYS:
        GameVariant.objects.filter(
            game__slug=GAME_SLUG,
            type="region",
            slug=slug,
        ).update(source_key="")


class Migration(migrations.Migration):
    dependencies = [
        ("posting", "0023_pool_offer_capacity_constraints"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
