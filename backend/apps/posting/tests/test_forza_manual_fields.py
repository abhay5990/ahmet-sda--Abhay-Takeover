"""Forza manual-entry and marketplace mapping regressions."""

from importlib import import_module

from apps.inventory.models import Category, Game, GamePlatformMapping
from apps.posting.models import GameVariant, GameVariantMapping
from django.apps import apps
from django.test import TestCase
from payload_pipeline.games.fh5.account.sources.manual import Fh5ManualSourceAdapter
from payload_pipeline.games.fh6.account.sources.manual import Fh6ManualSourceAdapter


class Fh5ManualFieldsTests(TestCase):
    def _parse(self, manual_fields):
        raw = {"loginData": {"login": "u", "password": "p"}, "manual_fields": manual_fields}
        return Fh5ManualSourceAdapter().parse(raw)

    def test_reads_platform_and_fields_from_manual_fields(self):
        src = self._parse({
            "platform": "PS5",
            "edition": "Premium",
            "cars_count": "150",
            "credits_count": "5000000",
        })
        self.assertEqual(src.platform, "PS5")
        self.assertEqual(src.edition, "Premium")
        self.assertEqual(src.cars_count, 150)
        self.assertEqual(src.credits_count, 5000000)

    def test_offer_details_still_supported(self):
        raw = {
            "loginData": {"login": "u", "password": "p"},
            "offer_details": {"platform": "Xbox", "cars_count": "10"},
        }
        src = Fh5ManualSourceAdapter().parse(raw)
        self.assertEqual(src.platform, "Xbox")
        self.assertEqual(src.cars_count, 10)


class ForzaEldoradoMappingSeedTests(TestCase):
    def test_mapping_upsert_idempotent(self):
        cat = Category.objects.create(name="forza-seed-cat", title="Forza Seed")
        game = Game.objects.create(name="Forza Horizon 5", slug="forza-horizon-5", category=cat)
        for _ in range(2):
            GamePlatformMapping.objects.update_or_create(
                platform="eldorado", external_id="106",
                defaults={"game": game, "external_name": "Forza Horizon 5"},
            )
        rows = GamePlatformMapping.objects.filter(platform="eldorado", external_id="106")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().game, game)


class Fh6ManualFieldsTests(TestCase):
    def test_reads_marketplace_fields_from_manual_fields(self):
        source = Fh6ManualSourceAdapter().parse({
            "loginData": {"login": "u", "password": "p"},
            "manual_fields": {
                "platform": "Xbox",
                "credits_count": "9000000",
                "all_cars": "Yes",
            },
        })
        self.assertEqual(source.platform, "Xbox")
        self.assertEqual(source.credits_count, 9000000)
        self.assertEqual(source.all_cars, "Yes")


class Fh6MarketplaceMappingSeedTests(TestCase):
    def test_seed_migrations_create_verified_mappings_and_platforms(self):
        category = Category.objects.create(name="fh6-support-cat", title="FH6 Support")
        game = Game.objects.create(
            name="Forza Horizon 6", slug="forza-horizon-6", category=category,
        )
        inventory_migration = import_module(
            "apps.inventory.migrations.0015_seed_fh6_marketplace_mappings",
        )
        posting_migration = import_module(
            "apps.posting.migrations.0036_seed_fh6_marketplace_platform_variants",
        )
        inventory_migration.seed_mappings(apps, None)
        posting_migration.seed_variants(apps, None)

        mappings = {
            row.platform: row.external_id
            for row in GamePlatformMapping.objects.filter(game=game)
        }
        self.assertEqual(mappings["gameboost"], "forza-horizon-6")
        self.assertEqual(mappings["playerauctions"], "15127")

        expected = {
            "pc": {"gameboost": "PC", "playerauctions": "15128"},
            "xbox": {"gameboost": "Xbox", "playerauctions": "15130"},
            "ps5": {"gameboost": "PS5", "playerauctions": "15129"},
        }
        for slug, marketplace_ids in expected.items():
            variant = GameVariant.objects.get(game=game, type="platform", slug=slug)
            actual = {
                row.marketplace: row.external_id
                for row in GameVariantMapping.objects.filter(variant=variant)
            }
            self.assertEqual(actual, marketplace_ids)
