"""Seed LOL region GameVariant + GameVariantMapping records if missing.

Migration 0010 seeds these as part of a bulk seed, but if the Game record
did not exist at migration time (e.g. on certain servers), the LOL entries
were silently skipped. This migration fills the gap idempotently.
"""

from django.db import migrations


LOL_REGIONS = [
    ("brazil", "Brazil", 0, "Brazil", {
        "eldorado": ("0", ""),
        "playerauctions": ("6001", "Brazil"),
        "gameboost": ("Brazil", ""),
    }),
    ("eune", "Europe Nordic & East", 1, "Europe Nordic & East", {
        "eldorado": ("1", ""),
        "playerauctions": ("4144", "EU Nordic and East"),
        "gameboost": ("Europe Nordic & East", ""),
    }),
    ("euw", "Europe West", 2, "Europe West", {
        "eldorado": ("2", ""),
        "playerauctions": ("4143", "EU West"),
        "gameboost": ("Europe West", ""),
    }),
    ("lan", "Latin America North", 3, "Latin America North", {
        "eldorado": ("3", ""),
        "playerauctions": ("5772", "Latin America North"),
        "gameboost": ("Latin America North", ""),
    }),
    ("las", "Latin America South", 4, "Latin America South", {
        "eldorado": ("4", ""),
        "playerauctions": ("5773", "Latin America South"),
        "gameboost": ("Latin America South", ""),
    }),
    ("oce", "Oceania", 5, "Oceania", {
        "eldorado": ("5", ""),
        "playerauctions": ("5769", "Oceania"),
        "gameboost": ("Oceania", ""),
    }),
    ("ru", "Russia", 6, "Russia", {
        "eldorado": ("6", ""),
        "playerauctions": ("5771", "Russia"),
        "gameboost": ("Russia", ""),
    }),
    ("tr", "Turkey", 7, "Turkey", {
        "eldorado": ("7", ""),
        "playerauctions": ("5770", "Turkey"),
        "gameboost": ("Turkey", ""),
    }),
    ("jp", "Japan", 8, "Japan", {
        "eldorado": ("8", ""),
        "playerauctions": ("8928", "Japan"),
        "gameboost": ("Japan", ""),
    }),
    ("na", "North America", 9, "North America", {
        "eldorado": ("9", ""),
        "playerauctions": ("3638", "North America"),
        "gameboost": ("North America", ""),
    }),
    ("ph", "Philippines", 10, "Philippines", {
        "eldorado": ("13", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Philippines", ""),
    }),
    ("sg", "Singapore, Malaysia & Indonesia", 11, "Singapore, Malaysia & Indonesia", {
        "eldorado": ("12", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Singapore", ""),
    }),
    ("th", "Thailand", 12, "Thailand", {
        "eldorado": ("15", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Thailand", ""),
    }),
    ("vn", "Vietnam", 13, "Vietnam", {
        "eldorado": ("14", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Vietnam", ""),
    }),
    ("me", "Middle East", 14, "Middle East", {
        "playerauctions": ("13870", "Middle East"),
    }),
    ("pbe", "PBE", 15, "PBE", {
        "playerauctions": ("8605", "PBE"),
    }),
]


def seed_lol_regions(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GameVariant = apps.get_model("posting", "GameVariant")
    GameVariantMapping = apps.get_model("posting", "GameVariantMapping")

    try:
        game = Game.objects.get(slug="league-of-legends")
    except Game.DoesNotExist:
        return  # game not in DB — nothing to do

    for slug, label, sort_order, source_key, mappings in LOL_REGIONS:
        variant, created = GameVariant.objects.get_or_create(
            game=game,
            type="region",
            slug=slug,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "source_key": source_key,
            },
        )
        for marketplace, (ext_id, ext_name) in mappings.items():
            GameVariantMapping.objects.get_or_create(
                variant=variant,
                marketplace=marketplace,
                defaults={
                    "external_id": ext_id,
                    "external_name": ext_name,
                },
            )


def reverse(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GameVariant = apps.get_model("posting", "GameVariant")

    try:
        game = Game.objects.get(slug="league-of-legends")
    except Game.DoesNotExist:
        return

    GameVariant.objects.filter(game=game, type="region").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("posting", "0016_add_consumed_to_offerpoolitemstatus"),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_lol_regions, reverse),
    ]
