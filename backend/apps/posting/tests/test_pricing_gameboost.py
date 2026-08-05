"""GameBoost prices must be converted USD->EUR; other marketplaces stay USD."""
from apps.posting.services.shared.pricing import (
    DEFAULT_GAMEBOOST_USD_TO_EUR,
    STOCK_PRICING_BASELINE,
    resolve_pricing_for_marketplace,
)
from django.test import SimpleTestCase


class ResolvePricingForMarketplaceTests(SimpleTestCase):
    def test_gameboost_gets_default_rate_when_none(self):
        p = resolve_pricing_for_marketplace(STOCK_PRICING_BASELINE, "gameboost")
        self.assertEqual(p.exchange_rate, DEFAULT_GAMEBOOST_USD_TO_EUR)

    def test_gameboost_respects_explicit_rate(self):
        base = STOCK_PRICING_BASELINE.with_overrides({"exchange_rate": 0.9})
        p = resolve_pricing_for_marketplace(base, "gameboost")
        self.assertEqual(p.exchange_rate, 0.9)

    def test_eldorado_stays_usd(self):
        p = resolve_pricing_for_marketplace(STOCK_PRICING_BASELINE, "eldorado")
        self.assertIsNone(p.exchange_rate)

    def test_playerauctions_stays_usd(self):
        p = resolve_pricing_for_marketplace(STOCK_PRICING_BASELINE, "playerauctions")
        self.assertIsNone(p.exchange_rate)
