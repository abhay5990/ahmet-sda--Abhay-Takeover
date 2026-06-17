"""Seed GameVariant + GameVariantMapping for FH5, New World, and Rust."""

from django.db import migrations


# (slug, label, sort_order, source_key, {marketplace: (external_id, external_name)})
FH5_PLATFORM = [
    ('pc', 'PC', 0, 'PC', {
        'eldorado': ('0', ''),
        'playerauctions': ('10636', 'PC'),
        'gameboost': ('PC', ''),
    }),
    ('xbox', 'Xbox', 1, 'Xbox', {
        'eldorado': ('1', ''),
        'playerauctions': ('10637', 'Xbox'),
        'gameboost': ('Xbox', ''),
    }),
    ('ps5', 'PS5', 2, 'PS5', {
        'eldorado': ('2', ''),
        'playerauctions': ('14295', 'PS'),
        'gameboost': ('PS5', ''),
    }),
]

NW_REGION = [
    ('us-east', 'US-East', 0, 'US-East', {
        'eldorado': ('0', ''),
        'playerauctions': ('9920', 'US East'),
    }),
    ('us-west', 'US-West', 1, 'US-West', {
        'eldorado': ('1', ''),
        'playerauctions': ('9916', 'US West'),
    }),
    ('ap-southeast', 'AP Southeast', 2, 'AP Southeast', {
        'eldorado': ('2', ''),
        'playerauctions': ('9917', 'AP Southeast'),
    }),
    ('sa-east', 'SA East', 3, 'SA East', {
        'eldorado': ('3', ''),
        'playerauctions': ('9918', 'SA East'),
    }),
    ('eu-central', 'EU-Central', 4, 'EU-Central', {
        'eldorado': ('4', ''),
        'playerauctions': ('9919', 'EU Central'),
    }),
]

RUST_PLATFORM = [
    ('pc', 'PC', 0, 'PC', {
        'eldorado': ('0', ''),
        'gameboost': ('PC', ''),
    }),
    ('playstation', 'PlayStation', 1, 'PlayStation', {
        'eldorado': ('1', ''),
        'gameboost': ('PlayStation', ''),
    }),
    ('xbox', 'Xbox', 2, 'Xbox', {
        'eldorado': ('2', ''),
        'gameboost': ('Xbox', ''),
    }),
]

GAME_SEED = [
    ('forza-horizon-5', 'platform', FH5_PLATFORM),
    ('new-world', 'region', NW_REGION),
    ('rust', 'platform', RUST_PLATFORM),
]


def seed_variants(apps, schema_editor):
    Game = apps.get_model('inventory', 'Game')
    GameVariant = apps.get_model('posting', 'GameVariant')
    GameVariantMapping = apps.get_model('posting', 'GameVariantMapping')

    for game_slug, variant_type, variants in GAME_SEED:
        game = Game.objects.filter(slug=game_slug).first()
        if not game:
            continue

        for slug, label, sort_order, source_key, mappings in variants:
            variant, _ = GameVariant.objects.update_or_create(
                game=game,
                type=variant_type,
                slug=slug,
                defaults={
                    'label': label,
                    'sort_order': sort_order,
                    'source_key': source_key,
                },
            )
            for marketplace, (external_id, external_name) in mappings.items():
                GameVariantMapping.objects.update_or_create(
                    variant=variant,
                    marketplace=marketplace,
                    defaults={
                        'external_id': external_id,
                        'external_name': external_name,
                    },
                )


def reverse_variants(apps, schema_editor):
    Game = apps.get_model('inventory', 'Game')
    GameVariant = apps.get_model('posting', 'GameVariant')

    for game_slug, variant_type, _ in GAME_SEED:
        game = Game.objects.filter(slug=game_slug).first()
        if not game:
            continue
        GameVariant.objects.filter(game=game, type=variant_type).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0017_seed_lol_region_variants'),
        ('inventory', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_variants, reverse_variants),
    ]
