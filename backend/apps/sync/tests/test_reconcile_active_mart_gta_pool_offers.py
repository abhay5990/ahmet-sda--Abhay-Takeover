from types import SimpleNamespace
from unittest.mock import Mock

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.sync.management.commands.reconcile_active_mart_gta_pool_offers import (
    Command,
    MAX_LIMIT,
    _active_offer_ids_from_snapshot,
    _snapshot_is_fresh,
)


class MartGtaPoolSnapshotProofTests(SimpleTestCase):
    def test_command_accepts_exact_pool_scope(self):
        command = Command()
        parser = command.create_parser("manage.py", "reconcile_active_mart_gta_pool_offers")

        options = parser.parse_args(["--pool-id", "80", "--limit", "39"])

        self.assertEqual(options.pool_id, 80)
        self.assertEqual(options.limit, 39)

    def test_accepts_only_fresh_exact_active_ids_and_batches_requests(self):
        client = Mock()
        client.list_offers.side_effect = [
            SimpleNamespace(
                ok=True,
                data=[{"offerId": 101}],
                meta={"snapshot_age_seconds": 31},
            ),
            SimpleNamespace(
                ok=True,
                data=[{"offerId": 202}],
                meta={"snapshot_age_seconds": 42},
            ),
        ]
        offer_ids = [str(value) for value in range(1, MAX_LIMIT + 2)]
        offer_ids[0] = "101"
        offer_ids[-1] = "202"

        proof = _active_offer_ids_from_snapshot(
            client,
            offer_ids,
            max_age_seconds=60,
        )

        self.assertEqual(proof.active_offer_ids, frozenset({"101", "202"}))
        self.assertEqual(proof.age_seconds, 42)
        self.assertEqual(client.list_offers.call_count, 2)
        self.assertEqual(client.list_offers.call_args_list[0].kwargs["listing_status"], "Active")
        self.assertEqual(client.list_offers.call_args_list[0].kwargs["page_size"], MAX_LIMIT)
        self.assertEqual(client.list_offers.call_args_list[1].kwargs["page_size"], 1)

    def test_refuses_stale_or_missing_snapshot_age(self):
        client = Mock()
        client.list_offers.return_value = SimpleNamespace(
            ok=True,
            data=[],
            meta={"snapshot_age_seconds": 601},
        )

        with self.assertRaisesRegex(CommandError, "stale or has no age proof"):
            _active_offer_ids_from_snapshot(client, ["101"], max_age_seconds=600)

        self.assertTrue(_snapshot_is_fresh(0, 600))
        self.assertTrue(_snapshot_is_fresh("600", 600))
        self.assertFalse(_snapshot_is_fresh(None, 600))
        self.assertFalse(_snapshot_is_fresh(-1, 600))

    def test_refuses_snapshot_transport_or_provider_failure(self):
        client = Mock()
        client.list_offers.return_value = SimpleNamespace(
            ok=False,
            error=SimpleNamespace(message="official_mart_snapshot_unavailable"),
        )

        with self.assertRaisesRegex(CommandError, "no pool state was changed"):
            _active_offer_ids_from_snapshot(client, ["101"], max_age_seconds=600)
