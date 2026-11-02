"""Only selected stores (default: GameBoost GI) use the proxy pool (Nov 2026)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from apps.integrations.providers import registry


def _cred(pk: int, slug: str):
    return SimpleNamespace(pk=pk, account=SimpleNamespace(slug=slug))


class ProxyOnlySelectedStoresTests(TestCase):
    def setUp(self):
        registry._client_cache.clear()

    def tearDown(self):
        registry._client_cache.clear()

    def test_default_only_gamerinstanty_uses_proxy(self):
        env = {}
        self.assertTrue(registry.store_uses_proxy(_cred(1, "gameboost-gamerinstanty"), env))
        for slug in ["eldorado-ezsmurfmart", "eldorado-ezsmurfshop", "gameboost-ezsmurfmart", "lzt-akashwork23", "playerauctions-csgosmurfkings"]:
            self.assertFalse(registry.store_uses_proxy(_cred(2, slug), env), slug)

    def test_env_list_and_star(self):
        env = {"SDA_PROXY_STORE_SLUGS": " gameboost-gamerinstanty , Eldorado-EzsmurfShop "}
        self.assertTrue(registry.store_uses_proxy(_cred(1, "eldorado-ezsmurfshop"), env))
        self.assertFalse(registry.store_uses_proxy(_cred(1, "eldorado-ezsmurfmart"), env))
        self.assertTrue(registry.store_uses_proxy(_cred(1, "eldorado-ezsmurfmart"), {"SDA_PROXY_STORE_SLUGS": "*"}))
        self.assertFalse(registry.store_uses_proxy(SimpleNamespace(pk=1, account=None), {}))

    def test_eldorado_client_is_built_without_proxy_pool(self):
        captured = {}

        class FakeProvider:
            def build_client(self, credential, *, proxy_pool=None, proxy_group=None):
                captured[credential.account.slug] = (proxy_pool, proxy_group)
                return object()

        pool = object()
        with patch.object(registry, "get_provider", return_value=FakeProvider()), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SDA_PROXY_STORE_SLUGS", None)
            registry.get_or_build_client("eldorado", _cred(10, "eldorado-ezsmurfmart"), proxy_pool=pool, proxy_group="mainGroup")
            registry.get_or_build_client("gameboost", _cred(11, "gameboost-gamerinstanty"), proxy_pool=pool, proxy_group="secondGroup")
        self.assertEqual(captured["eldorado-ezsmurfmart"], (None, None))
        self.assertEqual(captured["gameboost-gamerinstanty"], (pool, "secondGroup"))
