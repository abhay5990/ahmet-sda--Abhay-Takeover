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


class PlayerAuctionsTargetIncreaseTests(SimpleTestCase):
    def test_pool_clone_code_is_unique_per_listing_attempt_and_replaces_old_code(self):
        from apps.posting.services.stock.pa_tracking import (
            append_tracking_code_for_code,
            extract_tracking_code,
            pool_clone_tracking_code,
        )

        pool = SimpleNamespace(pk=12)
        first_item = SimpleNamespace(pk=31)
        second_item = SimpleNamespace(pk=32)
        first_code = pool_clone_tracking_code(pool, first_item, "a1b2c3d4-0000-0000-0000-000000000000")
        second_code = pool_clone_tracking_code(pool, second_item, "deadbeef-0000-0000-0000-000000000000")

        self.assertNotEqual(first_code, second_code)
        self.assertEqual(extract_tracking_code(f"[{first_code}]"), first_code)
        self.assertEqual(
            append_tracking_code_for_code(
                "GTA 5 Online-PC - Steam - Enhanced [PA-J7-I41]",
                first_code,
            ),
            f"GTA 5 Online-PC - Steam - Enhanced [{first_code}]",
        )

    def test_target_template_keeps_existing_title_and_description_pattern(self):
        from apps.posting.services.pool.replenisher import _apply_pa_target_template

        pool = SimpleNamespace(
            listing=SimpleNamespace(
                title="GTA 5 Online-PC - Steam - Enhanced [PA-J7-I41]",
                raw_data={
                    "description": "Generic fallback description that must not replace the target pattern.",
                    "payload": {
                        "title": "Old generated title",
                        "offerDesc": "Existing customer-facing description pattern.",
                    },
                },
            ),
        )
        payload = {
            "title": "Generic rebuilt title",
            "offerDesc": "Generic rebuilt description",
        }

        result = _apply_pa_target_template(pool, payload)

        self.assertEqual(
            result["title"],
            "GTA 5 Online-PC - Steam - Enhanced [PA-J7-I41]",
        )
        self.assertEqual(
            result["offerDesc"],
            "Existing customer-facing description pattern.",
        )

    def test_pa_staff_edit_updates_the_nested_future_clone_template(self):
        from apps.posting.services.offer_editor import _raw_data_with_changes

        raw = {
            "payload": {
                "gameId": 123,
                "autoDelivery": {},
                "title": "Old target pattern",
                "offerDesc": "Old target description",
            },
            "details": {
                "gameId": 123,
                "autoDelivery": {},
                "title": "Old target pattern",
                "offerDesc": "Old target description",
            },
        }

        result = _raw_data_with_changes(
            raw,
            {
                "title": "Established target pattern",
                "description": "Established target description",
            },
        )

        self.assertEqual(result["payload"]["title"], "Established target pattern")
        self.assertEqual(result["payload"]["offerDesc"], "Established target description")
        self.assertEqual(result["details"]["title"], "Established target pattern")
        self.assertEqual(result["details"]["offerDesc"], "Established target description")


class PlayerAuctionsDeletionWorkflowTests(SimpleTestCase):
    def test_explicit_playerauctions_auth_rejections_are_detected(self):
        from apps.posting.services.pool.lifecycle import _is_playerauctions_auth_failure

        unauthorized = SimpleNamespace(
            error=SimpleNamespace(status_code=401, message="Unauthorized"),
        )
        forbidden = SimpleNamespace(
            error=SimpleNamespace(status_code=403, message="Forbidden"),
        )
        ordinary_failure = SimpleNamespace(
            error=SimpleNamespace(status_code=500, message="Temporary provider failure"),
        )

        self.assertTrue(_is_playerauctions_auth_failure(unauthorized))
        self.assertTrue(_is_playerauctions_auth_failure(forbidden))
        self.assertFalse(_is_playerauctions_auth_failure(ordinary_failure))

    def test_pa_delete_rebuilds_cached_client_once_after_unauthorized(self):
        from unittest.mock import Mock, patch
        from apps.posting.services.pool.lifecycle import _delete_pa_listing_with_fresh_auth_retry

        first_client = SimpleNamespace()
        second_client = SimpleNamespace(
            reset_auth_failure=Mock(),
            force_auth_refresh=Mock(return_value=True),
        )
        unauthorized = SimpleNamespace(
            ok=False,
            error=SimpleNamespace(status_code=401, message="Unauthorized"),
        )
        success = SimpleNamespace(ok=True, error=None)
        provider = SimpleNamespace(delete_listing=Mock(side_effect=[unauthorized, success]))
        pool_offer = SimpleNamespace(
            store=SimpleNamespace(credential=SimpleNamespace(pk=99)),
        )

        with patch(
            "apps.posting.services.pool.lifecycle._client",
            side_effect=[(first_client, "pa-store"), (second_client, "pa-store")],
        ) as build_client, patch(
            "apps.posting.services.pool.lifecycle.invalidate_client",
        ) as invalidate:
            result = _delete_pa_listing_with_fresh_auth_retry(
                pool_offer,
                provider,
                "292889808",
            )

        self.assertIs(result, success)
        self.assertEqual(build_client.call_count, 2)
        invalidate.assert_called_once_with(99)
        second_client.reset_auth_failure.assert_called_once_with()
        second_client.force_auth_refresh.assert_called_once_with()
        self.assertEqual(provider.delete_listing.call_count, 2)

    def test_only_playerauctions_clone_deletions_auto_release_stock(self):
        from apps.posting.services.pool.lifecycle import _should_auto_release_after_remote_removal

        self.assertTrue(_should_auto_release_after_remote_removal(SimpleNamespace(
            marketplace="playerauctions", strategy="clone",
        )))
        self.assertFalse(_should_auto_release_after_remote_removal(SimpleNamespace(
            marketplace="eldorado", strategy="append",
        )))
        self.assertFalse(_should_auto_release_after_remote_removal(SimpleNamespace(
            marketplace="playerauctions", strategy="append",
        )))


    def test_production_compatible_pa_client_can_force_auth_refresh(self):
        from unittest.mock import Mock
        from apps.posting.services.pool.lifecycle import _force_playerauctions_auth_refresh

        auth = SimpleNamespace(refresh=Mock(return_value=True))
        client = SimpleNamespace(_auth=auth)

        self.assertTrue(_force_playerauctions_auth_refresh(client))
        auth.refresh.assert_called_once_with()


class PlayerAuctionsManualReturnTests(SimpleTestCase):
    def test_manual_return_is_limited_to_individual_playerauctions_clones(self):
        from apps.posting.services.pool.lifecycle import can_force_return_to_available

        self.assertTrue(can_force_return_to_available(SimpleNamespace(
            marketplace="playerauctions", strategy="clone",
        )))
        self.assertFalse(can_force_return_to_available(SimpleNamespace(
            marketplace="playerauctions", strategy="append",
        )))
        self.assertFalse(can_force_return_to_available(SimpleNamespace(
            marketplace="eldorado", strategy="clone",
        )))

    def test_manual_return_keeps_confirmed_sale_evidence_as_a_hard_block(self):
        from contextlib import nullcontext
        from unittest.mock import Mock, patch
        from apps.posting.models import OfferPoolItemStatus
        from apps.posting.services.pool.lifecycle import force_return_pool_item_to_available

        pool_offer = SimpleNamespace(
            pk=12,
            marketplace="playerauctions",
            strategy="clone",
        )
        locked_item = SimpleNamespace(pk=31, status=OfferPoolItemStatus.PUSHED)
        pool_offer_manager = Mock()
        pool_offer_manager.select_related.return_value.get.return_value = pool_offer
        item_manager = Mock()
        item_manager.select_for_update.return_value.select_related.return_value.get.return_value = locked_item

        with patch(
            "apps.posting.services.pool.lifecycle.PoolOffer.objects",
            pool_offer_manager,
        ), patch(
            "apps.posting.services.pool.lifecycle.OfferPoolItem.objects",
            item_manager,
        ), patch(
            "apps.posting.services.pool.lifecycle.transaction.atomic",
            return_value=nullcontext(),
        ), patch(
            "apps.posting.services.pool.lifecycle._has_confirmed_sale_evidence",
            return_value=True,
        ):
            result = force_return_pool_item_to_available(
                pool_offer,
                SimpleNamespace(pk=31),
                listing=SimpleNamespace(pk=77),
            )

        self.assertFalse(result.ok)
        self.assertIn("Confirmed marketplace sale evidence", result.errors[0])
