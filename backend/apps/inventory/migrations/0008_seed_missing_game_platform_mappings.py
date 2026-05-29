from django.db import migrations


CATEGORIES = {
    'steam': {
        'category_id': 1,
        'name': 'steam',
        'title': 'Steam',
    },
    'roblox': {
        'category_id': 31,
        'name': 'roblox',
        'title': 'Roblox',
    },
    'uplay': {
        'category_id': 5,
        'name': 'uplay',
        'title': 'Uplay',
    },
}

GAMES = [
    {
        'slug': 'growtopia',
        'name': 'Growtopia',
        'acronym': None,
        'category': 'uplay',
    },
    {
        'slug': 'team-fortress-2',
        'name': 'Team Fortress 2',
        'acronym': 'TF2',
        'category': 'steam',
    },
    {
        'slug': 'blade-ball',
        'name': 'Blade Ball',
        'acronym': None,
        'category': 'roblox',
    },
    {
        'slug': 'murder-mystery-2',
        'name': 'Murder Mystery 2',
        'acronym': 'MM2',
        'category': 'roblox',
    },
    {
        'slug': 'steal-a-brainrot',
        'name': 'Steal A Brainrot',
        'acronym': None,
        'category': 'roblox',
    },
]

MAPPINGS = [
    ('roblox', 'eldorado', '206', 'Roblox Accessories'),
    ('rust', 'eldorado', '235', 'Rust Twitch Drops'),
    ('garena-free-fire', 'gameboost', '29', 'Free Fire'),
    ('steam', 'gameboost', '91', 'Steam Accounts'),
    ('growtopia', 'eldorado', '99', 'Growtopia'),
    ('team-fortress-2', 'eldorado', '113', 'Team Fortress 2'),
    ('blade-ball', 'eldorado', '203', 'Blade Ball'),
    ('murder-mystery-2', 'eldorado', '204', 'Murder Mystery 2'),
    ('steal-a-brainrot', 'eldorado', '259', 'Steal A Brainrot'),
]


def seed_missing_game_platform_mappings(apps, schema_editor):
    Category = apps.get_model('inventory', 'Category')
    Game = apps.get_model('inventory', 'Game')
    GamePlatformMapping = apps.get_model('inventory', 'GamePlatformMapping')

    categories = {}
    for key, data in CATEGORIES.items():
        category, _ = Category.objects.update_or_create(
            category_id=data['category_id'],
            defaults={
                'name': data['name'],
                'title': data['title'],
            },
        )
        categories[key] = category

    for data in GAMES:
        Game.objects.update_or_create(
            slug=data['slug'],
            defaults={
                'name': data['name'],
                'acronym': data['acronym'],
                'category': categories[data['category']],
                'is_active': True,
            },
        )

    steam = Game.objects.filter(slug='steam').first()
    if steam:
        invalid_steam_mapping = GamePlatformMapping.objects.filter(
            platform='gameboost',
            external_id='None',
            game=steam,
        )
        if GamePlatformMapping.objects.filter(
            platform='gameboost',
            external_id='91',
        ).exists():
            invalid_steam_mapping.delete()
        else:
            invalid_steam_mapping.update(
                external_id='91',
                external_name='Steam Accounts',
            )

    for game_slug, platform, external_id, external_name in MAPPINGS:
        try:
            game = Game.objects.get(slug=game_slug)
        except Game.DoesNotExist:
            continue
        GamePlatformMapping.objects.update_or_create(
            platform=platform,
            external_id=external_id,
            defaults={
                'game': game,
                'external_name': external_name,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0007_dropshipproduct_last_checked_at_idx'),
    ]

    operations = [
        migrations.RunPython(
            seed_missing_game_platform_mappings,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
