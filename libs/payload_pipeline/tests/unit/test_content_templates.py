"""Tests for structured content template rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from payload_pipeline.content_templates import (
    DictTemplateProvider,
    DictTemplateOverrideProvider,
    JsonFileTemplateProvider,
    TemplateManager,
    TemplateDescriptionGenerator,
    TemplateTitleGenerator,
    TemplateValidationError,
    validate_template_map,
)
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import MediaBundle, PipelineRequest
from payload_pipeline.core.enums import ListingKind
from payload_pipeline.games.roblox.account.content import RobloxComposer
from payload_pipeline.games.roblox.account.models import RobloxResolvedAccount


def test_title_template_renders_parts_conditions_lists_and_suffix() -> None:
    spec = {
        "separator": " | ",
        "max_length": 80,
        "suffix": "S4G",
        "parts": [
            {"field": "region"},
            {"template": "{skin_count} Skins", "when": {"gt": ["skin_count", 0]}},
            {"field": "rank", "when": {"neq": ["rank", "Unranked"]}},
            {"list": "priority_items", "limit": 2},
        ],
    }
    context = {
        "region": "EU",
        "skin_count": 81,
        "rank": "Gold",
        "priority_items": ["Prime Vandal", "Reaver Knife", "Ion Sheriff"],
    }

    title = TemplateTitleGenerator().generate(spec, context)

    assert title == "EU | 81 Skins | Gold | Prime Vandal | Reaver Knife | S4G"


def test_description_template_renders_blocks_sections_and_limits() -> None:
    spec = {
        "char_limit": 120,
        "blocks": [
            {"type": "line", "text": "Account Details:"},
            {"type": "line", "template": "Level: {level}"},
            {"type": "line", "template": "Hidden", "when": {"truthy": "missing_flag"}},
            {"type": "blank"},
            {
                "type": "section",
                "title": "Some Items:",
                "items": "items",
                "limit": 3,
                "join": ", ",
            },
        ],
    }
    context = {"level": 44, "items": ["A", "B", "C", "D"]}

    description = TemplateDescriptionGenerator().generate(spec, context)

    assert description == "Account Details:\nLevel: 44\n\nSome Items:\nA, B, C"


def test_template_validation_rejects_unknown_part_keys() -> None:
    spec = {
        "default": {
            "title": {
                "parts": [
                    {"template": "{level}", "typo": True},
                ],
            },
            "description": {
                "blocks": [
                    {"type": "line", "text": "Details"},
                ],
            },
        }
    }

    with pytest.raises(TemplateValidationError, match="unknown keys"):
        validate_template_map(spec)


def test_dict_template_provider_loads_validated_copy() -> None:
    source = {
        "default": {
            "title": {"parts": [{"text": "Original"}]},
            "description": {"blocks": [{"type": "line", "text": "Body"}]},
        }
    }

    loaded = DictTemplateProvider(source).load()
    loaded["default"]["title"]["parts"][0]["text"] = "Changed"

    assert source["default"]["title"]["parts"][0]["text"] == "Original"


def test_json_file_template_provider_loads_roblox_resource() -> None:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "payload_pipeline"
        / "games"
        / "roblox"
        / "account"
        / "resources"
        / "content_templates.json"
    )

    loaded = JsonFileTemplateProvider(template_path).load()

    assert "default" in loaded
    assert "g2g" in loaded
    assert loaded["default"]["title"]["parts"]


def test_template_manager_merges_default_db_and_runtime_overrides() -> None:
    defaults = DictTemplateProvider(
        {
            "default": {
                "title": {"parts": [{"text": "Default"}]},
                "description": {"blocks": [{"type": "line", "text": "Body"}]},
            },
            "g2g": {
                "title": {"parts": [{"text": "DB base"}]},
            },
        }
    )
    db_overrides = DictTemplateOverrideProvider(
        {
            "g2g": {
                "title": {"parts": [{"text": "DB override"}]},
            }
        }
    )
    manager = TemplateManager(defaults, override_provider=db_overrides)

    loaded = manager.load(
        overrides={
            "gameboost": {
                "title": {"parts": [{"text": "Runtime override"}]},
            }
        }
    )

    assert loaded["default"]["description"]["blocks"][0]["text"] == "Body"
    assert loaded["g2g"]["title"]["parts"][0]["text"] == "DB override"
    assert loaded["gameboost"]["title"]["parts"][0]["text"] == "Runtime override"


def test_roblox_composer_can_use_template_content_without_changing_default_path() -> None:
    account = RobloxResolvedAccount(
        item_id="rbx-1",
        price=10.0,
        roblox_id=12345,
        robux=5000,
        incoming_robux_total=1200,
        inventory_price=8500.50,
        ugc_limited_price=3200.0,
        offsale_count=42,
        register_date=946684800,
        username="abcd",
        game_pass_total_robux=777,
        age_verified=True,
    )
    request = PipelineRequest(
        game="roblox",
        kind=ListingKind.STOCK,
        context={ctx.USE_TEMPLATE_CONTENT: True},
    )

    draft = RobloxComposer().compose(account, request, MediaBundle())

    assert "\u25c6 Registered: 2000" in draft.default.title
    assert "Inventory: 8500 R$" in draft.default.title
    assert "\U0001f539 Username: abcd" in draft.default.description
    assert "INSTANT DELIVERY" in draft.default.description
    assert draft.content_for("gameboost").title.startswith("4 Letter, Registered 2000")
    assert draft.content_for("playerauctions").title.startswith("Roblox Account - 4 Letter")
    assert "8500 R$ Inv" in draft.content_for("playerauctions").title
    assert len(draft.content_for("playerauctions").title) <= 100
    assert draft.content_for("g2g").title.startswith("Roblox Account | 4 Letter")
    assert len(draft.content_for("g2g").title) <= 120


def test_roblox_template_content_accepts_context_overrides() -> None:
    account = RobloxResolvedAccount(
        item_id="rbx-1",
        price=10.0,
        roblox_id=12345,
        username="abc",
        incoming_robux_total=1200,
        inventory_price=8500.50,
        register_date=946684800,
        friends=12,
    )
    request = PipelineRequest(
        game="roblox",
        kind=ListingKind.STOCK,
        context={
            ctx.USE_TEMPLATE_CONTENT: True,
            ctx.CONTENT_TEMPLATE_OVERRIDES: {
                "g2g": {
                    "title": {
                        "separator": " / ",
                        "max_length": 120,
                        "parts": [
                            {"text": "Custom Roblox"},
                            {"field": "letter_label"},
                            {"template": "{friends} Friends"},
                        ],
                    }
                }
            },
        },
    )

    draft = RobloxComposer().compose(account, request, MediaBundle())

    assert draft.content_for("g2g").title == "Custom Roblox / 3 Letter / 12 Friends"
