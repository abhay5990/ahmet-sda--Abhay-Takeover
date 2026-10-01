"""Seed verified FH6 platform mappings for GameBoost and PlayerAuctions."""

from django.db import migrations


_FH6_PLATFORM = (
    ("pc", "PC", 0, "PC", {"gameboost": ("PC", ""), "playerauctions": ("15128", "PC")} ),
    ("xbox", "Xbox", 1, "Xbox", {"gameboost": ("Xbox", ""), "playerauctions": ("15130", "XBOX")} ),
    ("ps5", "PS5", 2, "PS5", {"gameboost": ("PS5", ""), "playerauctions": ("15129", "PS")} ),
)


def seed_variants(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GameVariant = apps.get_model("posting", "GameVariant")
    GameVariantMapping = apps.get_model("posting", "GameVariantMapping")
    game = Game.objects.filter(slug="forza-horizon-6").first()
    if game is None:
        return

    for slug, label, sort_order, source_key, mappings in _FH6_PLATFORM:
        variant, _ = GameVariant.objects.update_or_create(
            game=game,
            type="platform",
            slug=slug,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "source_key": source_key,
            },
        )
        for marketplace, (external_id, external_name) in mappings.items():
            GameVariantMapping.objects.update_or_create(
                variant=variant,
                marketplace=marketplace,
                defaults={"external_id": external_id, "external_name": external_name},
            )


def unseed_variants(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GameVariant = apps.get_model("posting", "GameVariant")
    game = Game.objects.filter(slug="forza-horizon-6").first()
    if game is not None:
        GameVariant.objects.filter(game=game, type="platform").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0015_seed_fh6_marketplace_mappings"),
        ("posting", "0035_manual_faulty_pool_transfer"),
    ]

    operations = [
        migrations.RunPython(seed_variants, unseed_variants),
    ]
