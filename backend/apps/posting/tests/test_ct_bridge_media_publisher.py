from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.posting.pipeline.ct_bridge_client import (
    CtBridgeMediaPublisher,
    CtBridgeResult,
    pop_bridge_result,
)
from payload_pipeline.core import context_keys as ctx_keys
from payload_pipeline.core.contracts import MediaBundle


class CtBridgeMediaPublisherTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.fallback = Mock()
        self.fallback.publish.return_value = MediaBundle(
            local_paths=["/tmp/selected.png"],
            external_urls=["https://example.test/selected.png"],
            album_url="https://example.test/album",
        )
        self.publisher = CtBridgeMediaPublisher(
            self.client,
            fallback_publisher=self.fallback,
        )

    def test_selected_image_override_uses_hosted_fallback_without_bridge_call(self):
        request = SimpleNamespace(
            context={
                ctx_keys.MEDIA_OVERRIDE_PATH: "/tmp/selected.png",
                "ct_bridge_source_id": "12345",
                "ct_bridge_game": "roblox",
            }
        )

        result = self.publisher.publish(["/tmp/selected.png"], request=request)

        self.client.fetch.assert_not_called()
        self.fallback.publish.assert_called_once_with(
            ["/tmp/selected.png"],
            request=request,
        )
        self.assertEqual(result.external_urls, ["https://example.test/selected.png"])
        self.assertEqual(result.album_url, "https://example.test/album")

    def test_missing_bridge_context_uses_hosted_fallback(self):
        request = SimpleNamespace(context={})

        result = self.publisher.publish(["/tmp/selected.png"], request=request)

        self.client.fetch.assert_not_called()
        self.assertEqual(result.external_urls, ["https://example.test/selected.png"])

    def test_bridge_failure_uses_hosted_fallback(self):
        self.client.fetch.return_value = None
        request = SimpleNamespace(
            context={
                "ct_bridge_source_id": "12345",
                "ct_bridge_game": "roblox",
                "ct_bridge_eldorado_store": "ezsmurfmart",
            }
        )

        result = self.publisher.publish(["/tmp/source.png"], request=request)

        self.client.fetch.assert_called_once_with(
            source_item_id="12345",
            game="roblox",
            eldorado_store="ezsmurfmart",
        )
        self.assertEqual(result.external_urls, ["https://example.test/selected.png"])

    def test_successful_source_bridge_result_does_not_use_fallback(self):
        bridge_result = CtBridgeResult(
            ok=True,
            source_item_id="12345",
            game="roblox",
            imageshack_album_url="https://images.example/album",
            gameboost_image_urls=["https://images.example/account.png"],
        )
        self.client.fetch.return_value = bridge_result
        request = SimpleNamespace(
            context={
                "ct_bridge_source_id": "12345",
                "ct_bridge_game": "roblox",
            }
        )

        result = self.publisher.publish(["/tmp/source.png"], request=request)

        self.fallback.publish.assert_not_called()
        self.assertEqual(result.external_urls, ["https://images.example/account.png"])
        self.assertEqual(result.album_url, "https://images.example/album")
        self.assertIs(pop_bridge_result("12345", "roblox"), bridge_result)
