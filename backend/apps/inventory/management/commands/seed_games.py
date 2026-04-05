import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.inventory.models import Category, Game, GamePlatformMapping


class Command(BaseCommand):
    help = 'Seed categories, games, and platform mappings from JSON'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            default=str(Path(settings.BASE_DIR) / 'data' / 'game_mapp.json'),
            help='Path to the game mapping JSON file',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        games_data = data['games']

        # 1. Seed categories from unique lztCategory values
        categories_seen = {}
        for g in games_data:
            lzt = g.get('lztCategory')
            if lzt and lzt['id'] not in categories_seen:
                categories_seen[lzt['id']] = lzt['name']

        cat_count = 0
        for cat_id, cat_name in categories_seen.items():
            _, created = Category.objects.update_or_create(
                category_id=cat_id,
                defaults={
                    'name': slugify(cat_name),
                    'title': cat_name,
                },
            )
            if created:
                cat_count += 1
        self.stdout.write(f'Categories: {cat_count} created, {len(categories_seen) - cat_count} updated')

        # 2. Seed games
        game_count = 0
        for g in games_data:
            lzt = g.get('lztCategory')
            category = None
            if lzt:
                category = Category.objects.filter(category_id=lzt['id']).first()

            acronym = g.get('acronym') or None  # convert empty string to None

            _, created = Game.objects.update_or_create(
                slug=g['slug'],
                defaults={
                    'name': g['name'],
                    'acronym': acronym,
                    'category': category,
                },
            )
            if created:
                game_count += 1
        self.stdout.write(f'Games: {game_count} created, {len(games_data) - game_count} updated')

        # 3. Seed platform mappings
        mapping_count = 0
        platform_extractors = {
            'eldorado': lambda p: (str(p['gameId']), p.get('name', '')),
            'gameboost': lambda p: (str(p['id']), p.get('name', '')),
            'playerauctions': lambda p: (str(p['gameId']), p.get('name', '')),
        }

        for g in games_data:
            game = Game.objects.get(slug=g['slug'])
            platforms = g.get('platforms', {})

            for platform_key, extractor in platform_extractors.items():
                platform_data = platforms.get(platform_key)
                if not platform_data:
                    continue

                external_id, external_name = extractor(platform_data)
                _, created = GamePlatformMapping.objects.update_or_create(
                    platform=platform_key,
                    external_id=external_id,
                    defaults={
                        'game': game,
                        'external_name': external_name,
                    },
                )
                if created:
                    mapping_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Seed complete. Mappings: {mapping_count} created'
        ))
