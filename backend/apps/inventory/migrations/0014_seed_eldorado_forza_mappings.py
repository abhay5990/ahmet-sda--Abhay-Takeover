"""Seed Eldorado account GamePlatformMappings for Forza Horizon 5 and 6.

Enables the Eldorado store for these games in the manual stock UI and lets
Eldorado order/offer sync resolve them. Not used for the build-time gameId
(builders hardcode 106 / 414). Idempotent and defensive: only seeds when the
Game row exists.
"""
from django.db import migrations

_ELDORADO_ACCOUNT_MAPPINGS = {
    "forza-horizon-5": ("106", "Forza Horizon 5"),
    "forza-horizon-6": ("414", "Forza Horizon 6"),
}


def seed(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GamePlatformMapping = apps.get_model("inventory", "GamePlatformMapping")

    for slug, (external_id, external_name) in _ELDORADO_ACCOUNT_MAPPINGS.items():
        game = Game.objects.filter(slug=slug).first()
        if game is None:
            continue
        GamePlatformMapping.objects.update_or_create(
            platform="eldorado",
            external_id=external_id,
            defaults={"game": game, "external_name": external_name},
        )


def unseed(apps, schema_editor):
    GamePlatformMapping = apps.get_model("inventory", "GamePlatformMapping")
    GamePlatformMapping.objects.filter(
        platform="eldorado",
        external_id__in=[v[0] for v in _ELDORADO_ACCOUNT_MAPPINGS.values()],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0013_seed_eldorado_account_mappings"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
