"""Validation for structured content templates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class TemplateValidationError(ValueError):
    """Raised when a structured content template has an invalid shape."""


def validate_template_map(templates: Mapping[str, Any]) -> None:
    """Validate a marketplace-keyed template map.

    Expected shape:

    ``{"default": {"title": {...}, "description": {...}}, "g2g": {"title": {...}}}``
    """
    if not isinstance(templates, Mapping):
        raise TemplateValidationError("template map must be an object")
    if "default" not in templates:
        raise TemplateValidationError("template map must define a default template")

    for name, template in templates.items():
        if not isinstance(name, str) or not name:
            raise TemplateValidationError("template map keys must be non-empty strings")
        if not isinstance(template, Mapping):
            raise TemplateValidationError(f"{name} template must be an object")
        _validate_content_template(name, template, require_description=name == "default")


def _validate_content_template(
    name: str,
    template: Mapping[str, Any],
    *,
    require_description: bool,
) -> None:
    _reject_unknown(template, {"title", "description"}, f"{name} template")
    if "title" not in template and "description" not in template:
        raise TemplateValidationError(f"{name} template must define title or description")
    if require_description and "description" not in template:
        raise TemplateValidationError("default template must define description")
    if "title" in template:
        _validate_title(f"{name}.title", template["title"])
    if "description" in template:
        _validate_description(f"{name}.description", template["description"])


def _validate_title(path: str, spec: Any) -> None:
    if not isinstance(spec, Mapping):
        raise TemplateValidationError(f"{path} must be an object")
    _reject_unknown(
        spec,
        {"separator", "max_length", "suffix", "parts"},
        path,
    )
    if "separator" in spec and not isinstance(spec["separator"], str):
        raise TemplateValidationError(f"{path}.separator must be a string")
    if "suffix" in spec and spec["suffix"] is not None and not isinstance(spec["suffix"], str):
        raise TemplateValidationError(f"{path}.suffix must be a string or null")
    if "max_length" in spec:
        _validate_positive_int(f"{path}.max_length", spec["max_length"])

    parts = spec.get("parts")
    if not isinstance(parts, list) or not parts:
        raise TemplateValidationError(f"{path}.parts must be a non-empty list")
    for index, part in enumerate(parts):
        _validate_title_part(f"{path}.parts[{index}]", part)


def _validate_title_part(path: str, part: Any) -> None:
    if not isinstance(part, Mapping):
        raise TemplateValidationError(f"{path} must be an object")
    _reject_unknown(
        part,
        {
            "field",
            "template",
            "text",
            "list",
            "item_template",
            "limit",
            "when",
            "prefix",
            "suffix",
            "truncate",
        },
        path,
    )
    _validate_one_render_source(path, part, {"field", "template", "text", "list"})
    if "field" in part:
        _validate_field_ref(f"{path}.field", part["field"])
    if "template" in part and not isinstance(part["template"], str):
        raise TemplateValidationError(f"{path}.template must be a string")
    if "text" in part and not isinstance(part["text"], str):
        raise TemplateValidationError(f"{path}.text must be a string")
    if "list" in part:
        _validate_field_ref(f"{path}.list", part["list"])
    if "item_template" in part and not isinstance(part["item_template"], str):
        raise TemplateValidationError(f"{path}.item_template must be a string")
    if "limit" in part:
        _validate_positive_int(f"{path}.limit", part["limit"])
    if "prefix" in part and not isinstance(part["prefix"], str):
        raise TemplateValidationError(f"{path}.prefix must be a string")
    if "suffix" in part and not isinstance(part["suffix"], str):
        raise TemplateValidationError(f"{path}.suffix must be a string")
    if "truncate" in part and not isinstance(part["truncate"], bool):
        raise TemplateValidationError(f"{path}.truncate must be a boolean")
    if "when" in part:
        _validate_condition(f"{path}.when", part["when"])


def _validate_description(path: str, spec: Any) -> None:
    if not isinstance(spec, Mapping):
        raise TemplateValidationError(f"{path} must be an object")
    _reject_unknown(spec, {"char_limit", "newline", "blocks"}, path)
    if "char_limit" in spec:
        _validate_positive_int(f"{path}.char_limit", spec["char_limit"])
    if "newline" in spec and not isinstance(spec["newline"], str):
        raise TemplateValidationError(f"{path}.newline must be a string")

    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise TemplateValidationError(f"{path}.blocks must be a non-empty list")
    for index, block in enumerate(blocks):
        _validate_block(f"{path}.blocks[{index}]", block)


def _validate_block(path: str, block: Any) -> None:
    if not isinstance(block, Mapping):
        raise TemplateValidationError(f"{path} must be an object")
    block_type = block.get("type", "line")
    if block_type not in {"blank", "line", "lines", "section"}:
        raise TemplateValidationError(f"{path}.type is not supported: {block_type}")

    if block_type == "blank":
        _reject_unknown(block, {"type", "when"}, path)
    elif block_type == "line":
        _validate_line(path, block, required_source=True)
    elif block_type == "lines":
        _reject_unknown(block, {"type", "items", "when"}, path)
        items = block.get("items")
        if not isinstance(items, list):
            raise TemplateValidationError(f"{path}.items must be a list")
        for index, item in enumerate(items):
            if isinstance(item, Mapping):
                _validate_line(f"{path}.items[{index}]", item, required_source=True)
            elif not isinstance(item, str):
                raise TemplateValidationError(f"{path}.items[{index}] must be a string or line object")
    elif block_type == "section":
        _reject_unknown(
            block,
            {"type", "title", "items", "limit", "join", "trailing_blank", "when"},
            path,
        )
        if "title" in block and not isinstance(block["title"], str):
            raise TemplateValidationError(f"{path}.title must be a string")
        _validate_field_ref(f"{path}.items", block.get("items"))
        if "limit" in block:
            _validate_positive_int(f"{path}.limit", block["limit"])
        if "join" in block and not isinstance(block["join"], str):
            raise TemplateValidationError(f"{path}.join must be a string")
        if "trailing_blank" in block and not isinstance(block["trailing_blank"], bool):
            raise TemplateValidationError(f"{path}.trailing_blank must be a boolean")

    if "when" in block:
        _validate_condition(f"{path}.when", block["when"])


def _validate_line(path: str, line: Mapping[str, Any], *, required_source: bool) -> None:
    _reject_unknown(
        line,
        {"type", "field", "template", "text", "prefix", "suffix", "when"},
        path,
    )
    if required_source:
        _validate_one_render_source(path, line, {"field", "template", "text"})
    if "field" in line:
        _validate_field_ref(f"{path}.field", line["field"])
    if "template" in line and not isinstance(line["template"], str):
        raise TemplateValidationError(f"{path}.template must be a string")
    if "text" in line and not isinstance(line["text"], str):
        raise TemplateValidationError(f"{path}.text must be a string")
    if "prefix" in line and not isinstance(line["prefix"], str):
        raise TemplateValidationError(f"{path}.prefix must be a string")
    if "suffix" in line and not isinstance(line["suffix"], str):
        raise TemplateValidationError(f"{path}.suffix must be a string")
    if "when" in line:
        _validate_condition(f"{path}.when", line["when"])


def _validate_condition(path: str, condition: Any) -> None:
    if not isinstance(condition, Mapping):
        raise TemplateValidationError(f"{path} must be an object")
    if len(condition) != 1:
        raise TemplateValidationError(f"{path} must define exactly one operator")

    op, value = next(iter(condition.items()))
    if op in {"truthy", "falsy"}:
        _validate_field_ref(f"{path}.{op}", value)
        return
    if op in {"and", "or"}:
        if not isinstance(value, list) or not value:
            raise TemplateValidationError(f"{path}.{op} must be a non-empty list")
        for index, item in enumerate(value):
            _validate_condition(f"{path}.{op}[{index}]", item)
        return
    if op == "not":
        _validate_condition(f"{path}.not", value)
        return
    if op in {"gt", "gte", "lt", "lte", "eq", "neq", "contains"}:
        if not isinstance(value, list) or len(value) != 2:
            raise TemplateValidationError(f"{path}.{op} must be a two-item list")
        _validate_field_ref(f"{path}.{op}[0]", value[0])
        return

    raise TemplateValidationError(f"{path} has unsupported operator: {op}")


def _validate_one_render_source(
    path: str,
    value: Mapping[str, Any],
    keys: set[str],
) -> None:
    present = [key for key in keys if key in value]
    if len(present) != 1:
        joined = ", ".join(sorted(keys))
        raise TemplateValidationError(f"{path} must define exactly one of: {joined}")


def _validate_field_ref(path: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise TemplateValidationError(f"{path} must be a non-empty string")


def _validate_positive_int(path: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TemplateValidationError(f"{path} must be a positive integer")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        joined = ", ".join(unknown)
        raise TemplateValidationError(f"{path} has unknown keys: {joined}")
