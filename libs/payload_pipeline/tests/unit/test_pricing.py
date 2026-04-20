"""Tests for payload_pipeline.pricing and its integration into builders."""

from __future__ import annotations

from payload_pipeline.pricing import PricingRule, calculate_price
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline import PayloadPipeline, build_default_registry


# ── Unit tests for calculate_price ──────────────────────────────────────


def test_calculate_price_returns_raw_when_no_rule() -> None:
    assert calculate_price(5.0, None) == 5.0


def test_calculate_price_applies_low_multiplier() -> None:
    rule = PricingRule(multiplier_low=3.0, multiplier_mid=2.0, multiplier_high=1.5)
    # 5 * 3 = 15
    assert calculate_price(5.0, rule) == 15.0


def test_calculate_price_applies_mid_multiplier() -> None:
    rule = PricingRule(multiplier_low=3.0, multiplier_mid=2.0, multiplier_high=1.5)
    # 50 * 2 = 100
    assert calculate_price(50.0, rule) == 100.0


def test_calculate_price_applies_high_multiplier() -> None:
    rule = PricingRule(multiplier_low=3.0, multiplier_mid=2.0, multiplier_high=1.5)
    # 200 * 1.5 = 300
    assert calculate_price(200.0, rule) == 300.0


def test_calculate_price_applies_min_price() -> None:
    rule = PricingRule(multiplier_low=1.0, min_price=5.0)
    # 2 * 1.0 = 2, but min_price = 5
    assert calculate_price(2.0, rule) == 5.0


def test_calculate_price_applies_forced_ending() -> None:
    rule = PricingRule(multiplier_low=2.0, forced_ending=0.99)
    # 5 * 2 = 10, then forced ending → 10.99
    assert calculate_price(5.0, rule) == 10.99


def test_calculate_price_forced_ending_with_min_price() -> None:
    rule = PricingRule(multiplier_low=1.0, min_price=5.0, forced_ending=0.99)
    # 2 * 1 = 2, min_price → 5, then forced ending → 5.99
    assert calculate_price(2.0, rule) == 5.99


def test_calculate_price_ceils_fractional_result() -> None:
    rule = PricingRule(multiplier_low=2.5)
    # 3 * 2.5 = 7.5, ceil to 2 decimals = 7.5
    assert calculate_price(3.0, rule) == 7.5


def test_calculate_price_ceils_to_next_cent() -> None:
    rule = PricingRule(multiplier_low=1.333)
    # 7 * 1.333 = 9.331, ceil to 2 decimals = 9.34
    assert calculate_price(7.0, rule) == 9.34


def test_pricing_rule_is_immutable() -> None:
    rule = PricingRule(multiplier_low=2.0)
    try:
        rule.multiplier_low = 3.0  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_pricing_rule_boundary_at_10() -> None:
    rule = PricingRule(multiplier_low=3.0, multiplier_mid=2.0)
    assert rule.select_multiplier(10.0) == 3.0  # <= 10 → low
    assert rule.select_multiplier(10.01) == 2.0  # > 10 → mid


def test_pricing_rule_boundary_at_100() -> None:
    rule = PricingRule(multiplier_mid=2.0, multiplier_high=1.5)
    assert rule.select_multiplier(100.0) == 2.0   # <= 100 → mid
    assert rule.select_multiplier(100.01) == 1.5   # > 100 → high


# ── Integration test: pricing flows through Eldorado builder ────────────


def test_valorant_pipeline_applies_pricing_rule_to_payload(load_fixture) -> None:
    raw = load_fixture("lzt_val.json")
    pricing_rules = {
        "eldorado": PricingRule(multiplier_low=3.0, multiplier_mid=2.0, multiplier_high=1.5),
    }
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )
    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado", pricing_rules=pricing_rules))
    assert result.success

    raw_price = prepared.subject.price
    payload_price = result.payload["details"]["pricing"]["pricePerUnit"]["amount"]

    # pricing was applied — payload price should differ from raw
    if raw_price > 0:
        assert payload_price != raw_price or raw_price <= 0.1
    # payload price should be >= 0.1 (builder floor)
    assert payload_price >= 0.1


def test_pipeline_without_pricing_rule_uses_raw_price(load_fixture) -> None:
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )
    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
    assert result.success

    raw_price = prepared.subject.price
    payload_price = result.payload["details"]["pricing"]["pricePerUnit"]["amount"]
    # Without pricing rule, payload should use raw price (with builder's max(x, 0.1) and round)
    assert payload_price == round(max(raw_price, 0.1), 2)
