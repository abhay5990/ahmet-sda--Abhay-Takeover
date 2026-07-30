"""Seed Eldorado account GamePlatformMappings for the first manual-entry games.

These rows gate the Eldorado store in the manual stock UI and power order/offer
sync game resolution (they are NOT used for the build-time gameId, which the
payload builders hardcode). Idempotent and defensive: only seeds when the Game
row exists, and never overwrites a different existing mapping.
"""
from django.db import migrations

# slug -> (eldorado account gameId, verified API display name / gameSeoAlias base)
_ELDORADO_ACCOUNT_MAPPINGS = {
    "roblox": ("70", "Roblox"),
    "rust": ("37", "Rust"),
    "counter-strike-2": ("20", "Counter-Strike 2"),
    "rainbow-six-siege": ("48", "Rainbow Six Siege X"),
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
        ("inventory", "0012_source_product_id_to_charfield"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
