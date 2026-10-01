"""Seed verified Forza Horizon 6 GameBoost and PlayerAuctions mappings."""

from django.db import migrations


_MAPPINGS = (
    # GameBoost's account-offer API identifies the game with this verified slug.
    ("gameboost", "forza-horizon-6", "Forza Horizon 6"),
    # PlayerAuctions seller creation target, verified from public and authenticated read-only metadata.
    ("playerauctions", "15127", "Forza Horizon 6"),
)


def seed_mappings(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GamePlatformMapping = apps.get_model("inventory", "GamePlatformMapping")
    game = Game.objects.filter(slug="forza-horizon-6").first()
    if game is None:
        return

    for platform, external_id, external_name in _MAPPINGS:
        GamePlatformMapping.objects.update_or_create(
            platform=platform,
            external_id=external_id,
            defaults={"game": game, "external_name": external_name},
        )


def unseed_mappings(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GamePlatformMapping = apps.get_model("inventory", "GamePlatformMapping")
    game = Game.objects.filter(slug="forza-horizon-6").first()
    if game is None:
        return
    GamePlatformMapping.objects.filter(
        game=game,
        platform__in=[platform for platform, _, _ in _MAPPINGS],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0014_seed_eldorado_forza_mappings"),
    ]

    operations = [
        migrations.RunPython(seed_mappings, unseed_mappings),
    ]
