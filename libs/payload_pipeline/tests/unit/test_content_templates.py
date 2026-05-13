"""Tests for the {field_name} placeholder-based content template system."""

from __future__ import annotations

import pytest

from payload_pipeline.content_templates import (
    SimpleTemplateRenderer,
    TemplateRenderError,
    TemplateValidationError,
    compose_listing_draft,
    compose_with_templates,
    validate_template,
)
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
