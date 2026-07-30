"""Forza Horizon 5 manual entry must read the stock UI's manual_fields so the
selected platform drives the Eldorado trade environment (previously ignored)."""
from apps.inventory.models import Category, Game, GamePlatformMapping
from django.test import TestCase
from payload_pipeline.games.fh5.account.sources.manual import Fh5ManualSourceAdapter


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
