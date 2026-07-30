"""Rust manual-entry must read the stock UI's manual_fields and post correct
Eldorado attributes (the adapter previously only read offer_details)."""
from apps.inventory.models import Game, GamePlatformMapping
from django.test import TestCase
from payload_pipeline.games.rust.account.sources.manual import RustManualSourceAdapter


class RustManualFieldsTests(TestCase):
    def _parse(self, manual_fields):
        raw = {
            "loginData": {"login": "u", "password": "p"},
            "manual_fields": manual_fields,
        }
        return RustManualSourceAdapter().parse(raw)

    def test_reads_manual_fields_and_maps_premium_yes(self):
        src = self._parse({
            "platform": "Xbox",
            "premium_status": "Yes",
            "real_hours": "2500",
            "skins_count": "120",
            "steam_level": "30",
        })
        self.assertEqual(src.platform, "Xbox")
        self.assertEqual(src.premium_status, "premium-yes")
        self.assertEqual(src.real_hours, 2500)
        self.assertEqual(src.skins_count, 120)
        self.assertEqual(src.steam_level, 30)

    def test_premium_no_maps_to_premium_no(self):
        src = self._parse({"platform": "PC", "premium_status": "No", "real_hours": "10"})
        self.assertEqual(src.premium_status, "premium-no")

    def test_already_resolved_premium_id_passthrough(self):
        src = self._parse({"platform": "PC", "premium_status": "premium-other"})
        self.assertEqual(src.premium_status, "premium-other")

    def test_derived_eldorado_ranges_from_integers(self):
        """The builder derives Eldorado range ids from entered integers."""
        from payload_pipeline.games.rust.account.marketplaces.eldorado import (
            RustEldoradoBuilder,
        )
        b = RustEldoradoBuilder()
        # 2500h -> hours-2000, 120 skins -> skins-100, level 30 -> level-25
        self.assertEqual(b._resolve_hours(2500), "hours-2000")
        self.assertEqual(b._resolve_skins(120), "skins-100")
        self.assertEqual(b._resolve_steam_level(30), "level-25")


class EldoradoMappingSeedTests(TestCase):
    """The seed migration's upsert shape is idempotent when the Game exists."""

    def test_mapping_upsert_is_idempotent(self):
        from apps.inventory.models import Category

        cat = Category.objects.create(name="rust-seed-cat", title="Rust Seed")
        game = Game.objects.create(name="Rust", slug="rust", category=cat)
        for _ in range(2):
            GamePlatformMapping.objects.update_or_create(
                platform="eldorado", external_id="37",
                defaults={"game": game, "external_name": "Rust"},
            )
        rows = GamePlatformMapping.objects.filter(platform="eldorado", external_id="37")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().game, game)
