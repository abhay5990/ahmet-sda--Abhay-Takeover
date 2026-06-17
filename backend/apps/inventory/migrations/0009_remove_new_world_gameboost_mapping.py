from django.db import migrations


def remove_new_world_gameboost(apps, schema_editor):
    GamePlatformMapping = apps.get_model('inventory', 'GamePlatformMapping')
    GamePlatformMapping.objects.filter(
        game__slug='new-world',
        platform='gameboost',
    ).delete()


def restore_new_world_gameboost(apps, schema_editor):
    Game = apps.get_model('inventory', 'Game')
    GamePlatformMapping = apps.get_model('inventory', 'GamePlatformMapping')

    game = Game.objects.filter(slug='new-world').first()
    if not game:
        return

    GamePlatformMapping.objects.update_or_create(
        platform='gameboost',
        external_id='63',
        defaults={
            'game': game,
            'external_name': 'New World',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_seed_missing_game_platform_mappings'),
    ]

    operations = [
        migrations.RunPython(remove_new_world_gameboost, restore_new_world_gameboost),
    ]
