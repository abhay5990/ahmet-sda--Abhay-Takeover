"""Tests for the discover_eldorado_game management command (mocked HTTP)."""
import json
from io import StringIO
from unittest.mock import patch

from apps.inventory.models import Category, Game, GamePlatformMapping
from django.core.management import CommandError, call_command
from django.test import TestCase

_CMD = "apps.posting.management.commands.discover_eldorado_game"

_PAGE_1 = [
    {
        "category": "Account",
        "gameSeoAlias": "rust-accounts",
        "tradeEnvironmentValues": [{"name": "Device", "value": "PC", "id": "0"}],
        "attributes": [
            {"id": "rust-hours", "name": "Hours Played",
             "type": "Select", "value": {"id": "2000-plus", "name": "2000+"}},
        ],
    },
    {
        "category": "Account",
        "gameSeoAlias": "rust-accounts",
        "tradeEnvironmentValues": [{"name": "Device", "value": "Xbox", "id": "2"}],
        "attributes": [
            {"id": "rust-hours", "name": "Hours Played",
             "type": "Select", "value": {"id": "2000-plus", "name": "2000+"}},
        ],
    },
    # A leaked skin offer returned in an Account request — must group by its OWN category.
    {
        "category": "CustomItem",
        "gameSeoAlias": "rust-skins",
        "tradeEnvironmentValues": [],
        "attributes": [],
    },
]

_PAGE_2 = [
    {
        "category": "Account",
        "gameSeoAlias": "rust-accounts",
        "tradeEnvironmentValues": [{"name": "Device", "value": "PC", "id": "0"}],
        "attributes": [
            {"id": "rust-hours", "name": "Hours Played",
             "type": "Select", "value": {"id": "0-99", "name": "0-99"}},
        ],
    },
]


def _fake_pages(game_id, page, page_size):
    return {1: (200, _PAGE_1), 2: (200, _PAGE_2)}.get(page, (200, []))


class DiscoverEldoradoGameTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="acc", title="Acc")
        cls.game = Game.objects.create(name="Rust", slug="rust", category=cls.category)

    def _run(self, **kwargs):
        out = StringIO()
        with patch(f"{_CMD}.fetch_offers_page", side_effect=_fake_pages):
            call_command("discover_eldorado_game", stdout=out, stderr=StringIO(), **kwargs)
        return out.getvalue()

    def test_discovery_counts_grouped_by_returned_category(self):
        raw = self._run(game_id=37, pages=5, delay=0, as_json=True)
        summary = json.loads(raw)

        self.assertEqual(summary["offers_sampled"], 4)
        self.assertEqual(summary["dominant_alias"], "rust-accounts")

        # Grouped by each offer's OWN category — the skin offer is separate.
        self.assertIn("Account", summary["categories"])
        self.assertIn("CustomItem", summary["categories"])

        account = summary["categories"]["Account"]
        self.assertEqual(account["aliases"], {"rust-accounts": 3})
        # Frequency counts across pages: 2000+ seen twice, 0-99 once.
        hours = account["attributes"]["rust-hours"]["values"]
        self.assertEqual(hours["2000-plus"], 2)
        self.assertEqual(hours["0-99"], 1)
        # Trade-env options counted with their ids.
        self.assertEqual(account["trade_environments"]["Device|PC|0"], 2)
        self.assertEqual(account["trade_environments"]["Device|Xbox|2"], 1)

        self.assertEqual(summary["categories"]["CustomItem"]["aliases"], {"rust-skins": 1})

    def test_commit_persists_mapping_when_alias_matches(self):
        self._run(
            game_id=37, pages=2, delay=0,
            commit=True, game_slug="rust", expected_alias="rust-accounts",
        )
        mapping = GamePlatformMapping.objects.get(platform="eldorado", external_id="37")
        self.assertEqual(mapping.game, self.game)
        self.assertEqual(mapping.external_name, "rust-accounts")

    def test_commit_refuses_on_alias_mismatch(self):
        with self.assertRaises(CommandError):
            self._run(
                game_id=37, pages=2, delay=0,
                commit=True, game_slug="rust", expected_alias="wrong-alias",
            )
        self.assertFalse(
            GamePlatformMapping.objects.filter(platform="eldorado", external_id="37").exists()
        )

    def test_commit_requires_slug_and_expected_alias(self):
        with self.assertRaises(CommandError):
            self._run(game_id=37, pages=1, delay=0, commit=True)


class ResolveAliasTests(TestCase):
    def test_resolve_alias_extracts_game_id_near_alias(self):
        html = (
            '<script>{"foo":1,"gameSeoAlias":"red-dead-redemption-2-accounts",'
            '"gameId":"1234","bar":2}</script>'
            '<script>{"gameId":"999"}</script>'
        )
        out = StringIO()
        with patch(f"{_CMD}.fetch_listing_page_html", return_value=html):
            call_command(
                "discover_eldorado_game",
                resolve_alias="red-dead-redemption-2-accounts",
                as_json=True, stdout=out, stderr=StringIO(),
            )
        result = json.loads(out.getvalue())
        self.assertEqual(result["game_id"], 1234)

    def test_resolve_alias_returns_null_when_not_found(self):
        out = StringIO()
        with patch(f"{_CMD}.fetch_listing_page_html", return_value="<html>nothing</html>"):
            call_command(
                "discover_eldorado_game",
                resolve_alias="unknown-accounts",
                as_json=True, stdout=out, stderr=StringIO(),
            )
        self.assertIsNone(json.loads(out.getvalue())["game_id"])
