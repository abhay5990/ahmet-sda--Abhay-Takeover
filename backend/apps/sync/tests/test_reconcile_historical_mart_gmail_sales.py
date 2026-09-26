from types import SimpleNamespace

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.sync.management.commands.reconcile_historical_mart_gmail_sales import (
    DEFAULT_OBSERVED_FROM,
    DEFAULT_OBSERVED_TO,
    MAX_LIMIT,
    Command,
    _event_in_window,
    _utc_start_ms,
    _validated_limit,
)


class HistoricalMartGmailSaleReconcilerTests(SimpleTestCase):
    def test_defaults_to_the_bounded_september_window_and_dry_run(self):
        command = Command()
        parser = command.create_parser("manage.py", "reconcile_historical_mart_gmail_sales")

        options = parser.parse_args([])

        self.assertEqual(options.observed_from, DEFAULT_OBSERVED_FROM)
        self.assertEqual(options.observed_to, DEFAULT_OBSERVED_TO)
        self.assertEqual(options.limit, MAX_LIMIT)
        self.assertFalse(options.apply)

    def test_accepts_only_events_inside_the_explicit_window(self):
        start = _utc_start_ms("2026-09-01", option="--observed-from")
        end = _utc_start_ms("2026-10-01", option="--observed-to")

        self.assertFalse(_event_in_window(SimpleNamespace(observed_at_ms=start - 1), observed_from_ms=start, observed_to_ms=end))
        self.assertTrue(_event_in_window(SimpleNamespace(observed_at_ms=start), observed_from_ms=start, observed_to_ms=end))
        self.assertTrue(_event_in_window(SimpleNamespace(observed_at_ms=end - 1), observed_from_ms=start, observed_to_ms=end))
        self.assertFalse(_event_in_window(SimpleNamespace(observed_at_ms=end), observed_from_ms=start, observed_to_ms=end))

    def test_rejects_invalid_or_unbounded_limit_arguments(self):
        with self.assertRaisesRegex(CommandError, "--limit"):
            _validated_limit(0)
        with self.assertRaisesRegex(CommandError, "--limit"):
            _validated_limit(MAX_LIMIT + 1)

        with self.assertRaises(CommandError):
            _utc_start_ms("2026-09-31", option="--observed-from")

    def test_source_contains_no_marketplace_or_replenishment_write_path(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "management/commands/reconcile_historical_mart_gmail_sales.py"
        ).read_text()

        self.assertIn("allow_replenish=False", source)
        self.assertIn("dry-run by default", source.lower())
        self.assertNotIn("create_offer", source)
        self.assertNotIn("cancel_offer", source)
        self.assertNotIn("replenish_pool_offer", source)
