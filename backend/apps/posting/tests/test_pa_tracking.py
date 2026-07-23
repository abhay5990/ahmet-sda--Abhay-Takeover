from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.posting.services.shared.utils import extract_title_from_payload
from apps.posting.services.stock.pa_tracking import (
    append_tracking_code,
    extract_tracking_code,
    tracking_code_for_item,
)
from apps.sync.services.playerauctions.orders.service import _payload_text_values


class PlayerAuctionsTrackingTests(SimpleTestCase):
    def test_each_posting_item_has_a_unique_stable_code(self):
        first = SimpleNamespace(id=41, job_id=7)
        second = SimpleNamespace(id=42, job_id=7)

        self.assertEqual(tracking_code_for_item(first), "PA-J7-I41")
        self.assertNotEqual(tracking_code_for_item(first), tracking_code_for_item(second))
        self.assertEqual(
            append_tracking_code("Fortnite account", first),
            "Fortnite account [PA-J7-I41]",
        )

    def test_title_code_replaces_only_a_previous_generated_code(self):
        item = SimpleNamespace(id=9, job_id=3)

        title = append_tracking_code("Fortnite [PA-J1-I2] account", item)

        self.assertEqual(title, "Fortnite account [PA-J3-I9]")
        self.assertEqual(extract_tracking_code(title), "PA-J3-I9")

    def test_bulk_playerauctions_title_is_persisted_from_capitalized_column(self):
        payload = {"Title": "Valorant account [PA-J4-I12]"}

        self.assertEqual(
            extract_title_from_payload(payload, "playerauctions"),
            "Valorant account [PA-J4-I12]",
        )

    def test_order_code_can_be_found_in_nested_pa_payload_text(self):
        payload = {
            "order_info": {
                "offer_title": "Account [PA-J8-I99]",
            },
        }

        self.assertEqual(
            extract_tracking_code(*_payload_text_values(payload)),
            "PA-J8-I99",
        )


class PlayerAuctionsPayloadTrackingTests(SimpleTestCase):
    def _build_inputs(self, mode):
        item = SimpleNamespace(
            id=71,
            job_id=19,
            marketplace="playerauctions",
            store=SimpleNamespace(slug="pa-store"),
        )
        prepared = SimpleNamespace(
            subject=SimpleNamespace(price=20, main_platform="pc"),
        )
        job = SimpleNamespace(
            settings={"pa-store": {"pa_mode": mode}},
            game=SimpleNamespace(slug="fortnite"),
        )
        return item, {"prepared": prepared}, job

    def test_direct_pa_payload_gets_the_item_tracking_code(self):
        from unittest.mock import patch
        from apps.posting.services.stock.payload_builder import build_item_payload

        item, prepared_data, job = self._build_inputs("single")
        pipeline_result = SimpleNamespace(success=True, payload={"title": "Fortnite account"})
        with patch(
            "apps.posting.services.stock.payload_builder.adapter.build",
            return_value=pipeline_result,
        ):
            result = build_item_payload(item, prepared_data, job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["tracking_code"], "PA-J19-I71")
        self.assertEqual(
            result["data"]["payload"]["title"],
            "Fortnite account [PA-J19-I71]",
        )

    def test_bulk_pa_payload_gets_the_item_tracking_code(self):
        from unittest.mock import patch
        from apps.posting.services.stock.payload_builder import build_item_payload

        item, prepared_data, job = self._build_inputs("bulk")
        pipeline_result = SimpleNamespace(success=True, payload={"Title": "Fortnite account"})
        with patch(
            "apps.posting.services.stock.payload_builder.adapter.build_bulk",
            return_value=pipeline_result,
        ):
            result = build_item_payload(item, prepared_data, job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["tracking_code"], "PA-J19-I71")
        self.assertEqual(
            result["data"]["payload"]["Title"],
            "Fortnite account [PA-J19-I71]",
        )

    def test_recovery_service_and_route_are_available(self):
        from django.urls import reverse
        from apps.posting.services.pool.recovery import recover_verified_unsold_item

        self.assertTrue(callable(recover_verified_unsold_item))
        self.assertEqual(
            reverse(
                "posting:api_recover_unsold_pool_item",
                kwargs={"pool_id": 1, "item_id": 2},
            ),
            "/posting/api/pools/1/items/2/recover-unsold/",
        )
