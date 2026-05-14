"""Tests for the {field_name} placeholder-based content template system."""

from __future__ import annotations

import pytest

from payload_pipeline.content_templates import (
    ModifierError,
    SimpleTemplateRenderer,
    TemplateParseError,
    TemplateRenderError,
    TemplateValidationError,
    compose_listing_draft,
    compose_with_templates,
    validate_template,
)
from payload_pipeline.content_templates.parser import parse
from payload_pipeline.content_templates.ast_nodes import (
    Condition,
    IfBlockNode,
    Modifier,
    PlaceholderNode,
    TextNode,
)
from payload_pipeline.content_templates.modifiers import apply_modifier_chain
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import MediaBundle, PipelineRequest
from payload_pipeline.core.enums import ListingKind
from payload_pipeline.games.roblox.account.content import RobloxComposer
from payload_pipeline.games.roblox.account.models import RobloxResolvedAccount


# ---------------------------------------------------------------------------
# SimpleTemplateRenderer
# ---------------------------------------------------------------------------

def test_renderer_substitutes_placeholders() -> None:
    r = SimpleTemplateRenderer()
    assert r.render("{name} has {count} skins", {"name": "Alice", "count": 42}) == "Alice has 42 skins"


def test_renderer_none_becomes_empty_string() -> None:
    r = SimpleTemplateRenderer()
    assert r.render("Value: {v}", {"v": None}) == "Value: "


def test_renderer_bool_becomes_yes_no() -> None:
    r = SimpleTemplateRenderer()
    assert r.render("{a} / {b}", {"a": True, "b": False}) == "Yes / No"


def test_renderer_list_joins_with_comma() -> None:
    r = SimpleTemplateRenderer()
    assert r.render("Items: {items}", {"items": ["Sword", "Shield", "Ring"]}) == "Items: Sword, Shield, Ring"


def test_renderer_missing_field_becomes_empty_string() -> None:
    r = SimpleTemplateRenderer()
    assert r.render("Hello {missing}", {}) == "Hello "


def test_renderer_strict_mode_raises_on_missing_field() -> None:
    r = SimpleTemplateRenderer(strict=True)
    with pytest.raises(TemplateRenderError):
        r.render("Hello {missing}", {})


# ---------------------------------------------------------------------------
# validate_template
# ---------------------------------------------------------------------------

def test_validate_template_passes_valid_body() -> None:
    warnings = validate_template("Good title {name}", template_type="title")
    assert isinstance(warnings, list)


def test_validate_template_raises_on_multiline_title() -> None:
    with pytest.raises(TemplateValidationError, match="single"):
        validate_template("Line 1\nLine 2", template_type="title")


def test_validate_template_raises_on_max_length() -> None:
    with pytest.raises(TemplateValidationError, match="length"):
        validate_template("x" * 10, template_type="title", max_length=5)


def test_validate_template_warns_unknown_field() -> None:
    warnings = validate_template(
        "{totally_unknown_field}",
        template_type="title",
        available_fields={"price", "name"},
    )
    assert any("totally_unknown_field" in w for w in warnings)


def test_validate_template_raises_on_hyphen_placeholder() -> None:
    # {bad-field} passes brace balance but isn't a valid identifier — must error.
    with pytest.raises(TemplateValidationError, match="Invalid placeholder"):
        validate_template("{bad-field}", template_type="title")


def test_validate_template_raises_on_space_placeholder() -> None:
    with pytest.raises(TemplateValidationError, match="Invalid placeholder"):
        validate_template("{ space }", template_type="title")


def test_validate_template_raises_on_numeric_placeholder() -> None:
    with pytest.raises(TemplateValidationError, match="Invalid placeholder"):
        validate_template("{123abc}", template_type="title")


# ---------------------------------------------------------------------------
# compose_with_templates
# ---------------------------------------------------------------------------

def test_compose_with_templates_renders_per_marketplace() -> None:
    result = compose_with_templates(
        {"name": "Alice", "level": 99},
        title_templates={
            "eldorado": "Eldorado: {name} Lv{level}",
            "g2g": "G2G: {name}",
        },
    )
    assert result.marketplace_titles["eldorado"] == "Eldorado: Alice Lv99"
    assert result.marketplace_titles["g2g"] == "G2G: Alice"


def test_compose_with_templates_picks_default_from_eldorado() -> None:
    result = compose_with_templates(
        {"x": "val"},
        title_templates={"eldorado": "Default title", "g2g": "G2G title"},
    )
    assert result.default_title == "Default title"


def test_compose_with_templates_falls_back_to_first_when_no_eldorado() -> None:
    result = compose_with_templates(
        {},
        title_templates={"g2g": "Only G2G"},
    )
    assert result.default_title == "Only G2G"


def test_compose_with_templates_none_inputs_return_empty_result() -> None:
    result = compose_with_templates({}, title_templates=None, description_templates=None)
    assert result.default_title is None
    assert result.default_description is None
    assert result.marketplace_titles == {}


# ---------------------------------------------------------------------------
# compose_listing_draft
# ---------------------------------------------------------------------------

def test_compose_listing_draft_builds_draft_with_overrides() -> None:
    draft = compose_listing_draft(
        {"name": "Test"},
        title_templates={"eldorado": "El: {name}", "g2g": "G2G: {name}"},
        description_templates={"eldorado": "Desc for {name}"},
        media=MediaBundle(),
        tags=["test"],
    )
    assert draft.default.title == "El: Test"
    assert draft.default.description == "Desc for Test"
    assert draft.content_for("g2g").title == "G2G: Test"
    assert draft.content_for("g2g").description == "Desc for Test"  # falls back to default
    assert draft.default.tags == ["test"]


def test_compose_listing_draft_empty_templates_gives_empty_strings() -> None:
    draft = compose_listing_draft(
        {},
        title_templates=None,
        description_templates=None,
        media=MediaBundle(),
        tags=["game"],
    )
    assert draft.default.title == ""
    assert draft.default.description == ""
    assert draft.marketplace_overrides == {}


# ---------------------------------------------------------------------------
# RobloxComposer with TITLE_TEMPLATES / DESCRIPTION_TEMPLATES
# ---------------------------------------------------------------------------

def _make_roblox_account() -> RobloxResolvedAccount:
    return RobloxResolvedAccount(
        item_id="rbx-1",
        price=10.0,
        roblox_id=12345,
        username="abcd",
        inventory_price=8500.0,
        register_date=946684800,  # 2000-01-01
    )


def test_roblox_composer_uses_title_template_when_set() -> None:
    request = PipelineRequest(
        game="roblox",
        kind=ListingKind.STOCK,
        context={
            ctx.TITLE_TEMPLATES: {"eldorado": "Roblox {username} inv:{inventory_price_int}R$"},
        },
    )
    draft = RobloxComposer().compose(_make_roblox_account(), request, MediaBundle())
    # Template applies as a marketplace override; draft.default stays legacy
    assert draft.content_for("eldorado").title == "Roblox abcd inv:8500R$"


def test_roblox_composer_uses_desc_template_when_set() -> None:
    request = PipelineRequest(
        game="roblox",
        kind=ListingKind.STOCK,
        context={
            ctx.DESCRIPTION_TEMPLATES: {"eldorado": "User: {username}"},
        },
    )
    draft = RobloxComposer().compose(_make_roblox_account(), request, MediaBundle())
    # Template applies as a marketplace override; draft.default stays legacy
    assert draft.content_for("eldorado").description == "User: abcd"


def test_roblox_composer_marketplace_override_from_template() -> None:
    request = PipelineRequest(
        game="roblox",
        kind=ListingKind.STOCK,
        context={
            ctx.TITLE_TEMPLATES: {
                "eldorado": "El: {username}",
                "g2g": "G2G: {username}",
            },
        },
    )
    draft = RobloxComposer().compose(_make_roblox_account(), request, MediaBundle())
    assert draft.content_for("g2g").title == "G2G: abcd"
    assert draft.content_for("eldorado").title == "El: abcd"


def test_roblox_composer_falls_back_to_legacy_when_no_templates() -> None:
    request = PipelineRequest(
        game="roblox",
        kind=ListingKind.STOCK,
        context={},
    )
    draft = RobloxComposer().compose(_make_roblox_account(), request, MediaBundle())
    # Legacy path produces non-empty title
    assert len(draft.default.title) > 0


# ===========================================================================
# Phase 1: Parser Tests
# ===========================================================================

class TestParser:
    def test_simple_field(self) -> None:
        nodes = parse("{field}")
        assert nodes == (PlaceholderNode(field_name="field"),)

    def test_text_and_placeholder(self) -> None:
        nodes = parse("Hello {name}!")
        assert nodes == (
            TextNode("Hello "),
            PlaceholderNode(field_name="name"),
            TextNode("!"),
        )

    def test_field_with_single_modifier(self) -> None:
        nodes = parse("{field | limit:3}")
        assert nodes == (
            PlaceholderNode(field_name="field", modifiers=(Modifier("limit", "3"),)),
        )

    def test_field_with_chained_modifiers(self) -> None:
        nodes = parse("{field | limit:3 | join:-}")
        assert nodes == (
            PlaceholderNode(
                field_name="field",
                modifiers=(Modifier("limit", "3"), Modifier("join", "-")),
            ),
        )

    def test_modifier_no_arg(self) -> None:
        nodes = parse("{field | upper}")
        assert nodes == (
            PlaceholderNode(field_name="field", modifiers=(Modifier("upper", None),)),
        )

    def test_if_block_simple(self) -> None:
        nodes = parse("{#if field}text{/if}")
        assert len(nodes) == 1
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.condition == Condition("field", "truthy")
        assert node.if_body == (TextNode("text"),)
        assert node.else_body == ()

    def test_if_block_with_operator(self) -> None:
        nodes = parse("{#if level > 5}high{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.condition == Condition("level", ">", "5")

    def test_if_else_block(self) -> None:
        nodes = parse("{#if rank}{rank}{#else}Unranked{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.if_body == (PlaceholderNode("rank"),)
        assert node.else_body == (TextNode("Unranked"),)

    def test_nested_if_raises(self) -> None:
        with pytest.raises(TemplateParseError, match="Nested"):
            parse("{#if a}{#if b}x{/if}{/if}")

    def test_unmatched_endif_raises(self) -> None:
        with pytest.raises(TemplateParseError, match="Unexpected.*{/if}"):
            parse("{/if}")

    def test_unmatched_if_raises(self) -> None:
        with pytest.raises(TemplateParseError, match="Unclosed"):
            parse("{#if field}text")

    def test_else_outside_if_raises(self) -> None:
        with pytest.raises(TemplateParseError, match="Unexpected.*{#else}"):
            parse("{#else}")

    def test_condition_equals(self) -> None:
        nodes = parse("{#if platform = PC}yes{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.condition == Condition("platform", "=", "PC")

    def test_condition_not_equals(self) -> None:
        nodes = parse("{#if kind != dropshipping}yes{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.condition == Condition("kind", "!=", "dropshipping")

    def test_condition_gte(self) -> None:
        nodes = parse("{#if level >= 100}yes{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.condition == Condition("level", ">=", "100")

    def test_placeholder_inside_if(self) -> None:
        nodes = parse("{#if count}{count}x Items{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.if_body == (PlaceholderNode("count"), TextNode("x Items"))

    def test_modifier_inside_if(self) -> None:
        nodes = parse("{#if items}{items | limit:3}{/if}")
        node = nodes[0]
        assert isinstance(node, IfBlockNode)
        assert node.if_body == (
            PlaceholderNode("items", modifiers=(Modifier("limit", "3"),)),
        )

    def test_pure_text(self) -> None:
        nodes = parse("Just plain text")
        assert nodes == (TextNode("Just plain text"),)

    def test_empty_template(self) -> None:
        """Empty string: parser returns empty tuple (render() short-circuits before calling parse)."""
        nodes = parse("")
        assert nodes == ()

    def test_max_if_blocks_exceeded(self) -> None:
        template = "".join(f"{{#if f{i}}}x{{/if}}" for i in range(51))
        with pytest.raises(TemplateParseError, match="Too many"):
            parse(template)


# ===========================================================================
# Phase 1: Modifier Tests
# ===========================================================================

class TestModifiers:
    def test_limit_on_list(self) -> None:
        result = apply_modifier_chain(["A", "B", "C", "D"], (Modifier("limit", "3"),))
        assert result == ["A", "B", "C"]

    def test_limit_capped_at_100(self) -> None:
        big_list = list(range(200))
        result = apply_modifier_chain(big_list, (Modifier("limit", "999"),))
        assert len(result) == 100

    def test_limit_on_non_list_passthrough(self) -> None:
        result = apply_modifier_chain("hello", (Modifier("limit", "3"),))
        assert result == "hello"

    def test_join_on_list(self) -> None:
        result = apply_modifier_chain(["A", "B", "C"], (Modifier("join", "-"),))
        assert result == "A-B-C"

    def test_join_default_separator(self) -> None:
        result = apply_modifier_chain(["A", "B"], (Modifier("join", None),))
        assert result == "A, B"

    def test_upper(self) -> None:
        result = apply_modifier_chain("diamond", (Modifier("upper", None),))
        assert result == "DIAMOND"

    def test_lower(self) -> None:
        result = apply_modifier_chain("Diamond", (Modifier("lower", None),))
        assert result == "diamond"

    def test_default_on_none(self) -> None:
        result = apply_modifier_chain(None, (Modifier("default", "N/A"),))
        assert result == "N/A"

    def test_default_on_value(self) -> None:
        result = apply_modifier_chain("real", (Modifier("default", "N/A"),))
        assert result == "real"

    def test_default_on_empty_string(self) -> None:
        result = apply_modifier_chain("", (Modifier("default", "N/A"),))
        assert result == "N/A"

    def test_default_on_empty_list(self) -> None:
        result = apply_modifier_chain([], (Modifier("default", "None"),))
        assert result == "None"

    def test_prefix_truthy(self) -> None:
        result = apply_modifier_chain(5000, (Modifier("prefix", "BE: "),))
        assert result == "BE: 5000"

    def test_prefix_falsy(self) -> None:
        result = apply_modifier_chain(0, (Modifier("prefix", "BE: "),))
        assert result == ""

    def test_suffix_truthy(self) -> None:
        result = apply_modifier_chain(5000, (Modifier("suffix", " BE"),))
        assert result == "5000 BE"

    def test_suffix_falsy(self) -> None:
        result = apply_modifier_chain(None, (Modifier("suffix", " BE"),))
        assert result == ""

    def test_number_int(self) -> None:
        result = apply_modifier_chain(45000, (Modifier("number", None),))
        assert result == "45,000"

    def test_number_float(self) -> None:
        result = apply_modifier_chain(1234.5, (Modifier("number", None),))
        assert result == "1,234.50"

    def test_unknown_modifier_raises(self) -> None:
        with pytest.raises(ModifierError, match="Unknown modifier"):
            apply_modifier_chain("x", (Modifier("bogus", None),))

    def test_chain_limit_join(self) -> None:
        result = apply_modifier_chain(
            ["R4-C", "MP5", "416-C", "P90"],
            (Modifier("limit", "3"), Modifier("join", "-")),
        )
        assert result == "R4-C-MP5-416-C"


# ===========================================================================
# Phase 1: Render Integration Tests
# ===========================================================================

class TestConditionalRendering:
    def test_plain_field_unchanged(self) -> None:
        """Regression: existing {field} templates produce identical output."""
        r = SimpleTemplateRenderer()
        assert r.render("{name} Lv{level}", {"name": "Test", "level": 42}) == "Test Lv42"

    def test_field_with_modifier(self) -> None:
        r = SimpleTemplateRenderer()
        assert r.render("{rank | upper}", {"rank": "diamond"}) == "DIAMOND"

    def test_if_truthy(self) -> None:
        r = SimpleTemplateRenderer()
        assert r.render("{#if count}{count}x{/if}", {"count": 5}) == "5x"

    def test_if_falsy(self) -> None:
        r = SimpleTemplateRenderer()
        assert r.render("{#if count}{count}x{/if}", {"count": 0}) == ""

    def test_if_missing_field_is_falsy(self) -> None:
        r = SimpleTemplateRenderer()
        assert r.render("{#if count}{count}x{/if}", {}) == ""

    def test_if_gt(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if be > 5000}{be} BE{/if}"
        assert r.render(tpl, {"be": 6000}) == "6000 BE"
        assert r.render(tpl, {"be": 3000}) == ""

    def test_if_eq(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if platform = PC}Desktop{/if}"
        assert r.render(tpl, {"platform": "PC"}) == "Desktop"
        assert r.render(tpl, {"platform": "Console"}) == ""

    def test_if_neq(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if kind != dropshipping}Instant Delivery{/if}"
        assert r.render(tpl, {"kind": "stock"}) == "Instant Delivery"
        assert r.render(tpl, {"kind": "dropshipping"}) == ""

    def test_if_else_true_branch(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if rank}{rank}{#else}Unranked{/if}"
        assert r.render(tpl, {"rank": "Diamond"}) == "Diamond"

    def test_if_else_false_branch(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if rank}{rank}{#else}Unranked{/if}"
        assert r.render(tpl, {"rank": ""}) == "Unranked"

    def test_nested_placeholder_inside_conditional(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if count}{count}x Items{/if}"
        assert r.render(tpl, {"count": 12}) == "12x Items"
        assert r.render(tpl, {"count": 0}) == ""

    def test_modifier_inside_conditional(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if items}{items | limit:3 | join:, }{/if}"
        assert r.render(tpl, {"items": ["A", "B", "C", "D"]}) == "A, B, C"
        assert r.render(tpl, {"items": []}) == ""

    def test_extract_fields_includes_condition_fields(self) -> None:
        r = SimpleTemplateRenderer()
        fields = r.extract_fields("{#if count}{count}x{/if} | {name}")
        assert "count" in fields
        assert "name" in fields

    def test_full_r6_title_template(self) -> None:
        """RFC real-world example: R6 title template."""
        r = SimpleTemplateRenderer()
        tpl = (
            "[PC] | {#if level}Level {level}{/if} | "
            "{#if current_rank}{current_rank}{/if} | "
            "{#if black_ice_count}{black_ice_count}xBlack Ice{/if} | "
            "{#if black_ice_items}({black_ice_items | limit:3 | join:-}){/if} | "
            "Full Access | "
            "{#if kind != dropshipping}Instant Delivery{/if}"
        )
        # Rich account
        result = r.render(tpl, {
            "level": 120,
            "current_rank": "Diamond",
            "black_ice_count": 12,
            "black_ice_items": ["R4-C", "MP5", "416-C", "P90"],
            "kind": "stock",
        })
        assert "Level 120" in result
        assert "Diamond" in result
        assert "12xBlack Ice" in result
        assert "(R4-C-MP5-416-C)" in result
        assert "Instant Delivery" in result

        # Basic account (conditionals should be empty)
        result = r.render(tpl, {
            "level": 45,
            "current_rank": "Gold",
            "black_ice_count": 0,
            "black_ice_items": [],
            "kind": "dropshipping",
        })
        assert "Level 45" in result
        assert "Gold" in result
        assert "Black Ice" not in result
        assert "Instant Delivery" not in result

    def test_if_with_float_comparison(self) -> None:
        r = SimpleTemplateRenderer()
        assert r.render("{#if val > 0}yes{/if}", {"val": 0.5}) == "yes"
        assert r.render("{#if val > 0}yes{/if}", {"val": 0.0}) == ""

    def test_if_gte(self) -> None:
        r = SimpleTemplateRenderer()
        tpl = "{#if level >= 100}high{/if}"
        assert r.render(tpl, {"level": 100}) == "high"
        assert r.render(tpl, {"level": 99}) == ""


# ===========================================================================
# Phase 1: Validation Tests (new syntax)
# ===========================================================================

class TestValidationNewSyntax:
    def test_valid_modifier_template(self) -> None:
        warnings = validate_template("{field | upper}", template_type="title")
        assert isinstance(warnings, list)

    def test_valid_conditional_template(self) -> None:
        warnings = validate_template(
            "{#if count}{count}x{/if}", template_type="title"
        )
        assert isinstance(warnings, list)

    def test_nested_if_raises(self) -> None:
        with pytest.raises(TemplateValidationError):
            validate_template("{#if a}{#if b}x{/if}{/if}", template_type="title")

    def test_unmatched_if_raises(self) -> None:
        with pytest.raises(TemplateValidationError):
            validate_template("{#if field}text", template_type="title")

    def test_unknown_field_in_conditional(self) -> None:
        warnings = validate_template(
            "{#if mystery}text{/if}",
            template_type="title",
            available_fields={"name"},
        )
        assert any("mystery" in w for w in warnings)
