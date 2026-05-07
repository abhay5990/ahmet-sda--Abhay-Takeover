"""Small structured template renderer for listing content.

The renderer owns generic mechanics only:
* title parts, separators, suffixes, and max-length fitting
* description blocks, sections, conditions, and character limits

Game-specific decisions stay outside this module.  A game adapter should
prepare fields such as ``valuable_skins`` or ``register_year`` before calling
these generators.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


Context = Mapping[str, Any]
Spec = Mapping[str, Any]


class TemplateRenderError(ValueError):
    """Raised when a structured content template cannot be rendered."""


class _FormatContext(dict[str, Any]):
    def __init__(self, context: Context, *, strict: bool) -> None:
        super().__init__(context)
        self.strict = strict

    def __missing__(self, key: str) -> str:
        if self.strict:
            raise TemplateRenderError(f"Missing template field: {key}")
        return ""


class TemplateTitleGenerator:
    """Render a title from a structured ``parts`` spec."""

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict

    def generate(self, spec: Spec, context: Context) -> str:
        separator = str(spec.get("separator", " | "))
        max_length = _to_int(spec.get("max_length"), default=0)
        suffix = _string_or_empty(spec.get("suffix"))
        parts = spec.get("parts", [])
        if not isinstance(parts, list):
            raise TemplateRenderError("title.parts must be a list")

        built: list[str] = []
        current_length = 0
        reserved = len(suffix) + (len(separator) if suffix else 0)

        for raw_part in parts:
            if not isinstance(raw_part, Mapping):
                raise TemplateRenderError("title part must be an object")
            if not _condition_matches(raw_part.get("when"), context):
                continue

            rendered_parts = self._render_part(raw_part, context)
            for part in rendered_parts:
                item_len = len(part) + (len(separator) if built else 0)
                limit = max_length - reserved if max_length else 0
                if limit and current_length + item_len > limit:
                    if not built and raw_part.get("truncate"):
                        built.append(_truncate(part, limit))
                    break
                built.append(part)
                current_length += item_len

        if suffix:
            built.append(suffix)

        title = separator.join(p for p in built if p)
        if max_length and len(title) > max_length:
            title = _truncate(title, max_length)
        return title

    def _render_part(self, part: Spec, context: Context) -> list[str]:
        if "list" in part:
            values = _as_list(_get_value(context, str(part["list"])))
            limit = _to_int(part.get("limit"), default=0)
            if limit > 0:
                values = values[:limit]
            item_template = part.get("item_template")
            rendered = [
                _render_template(str(item_template), {**context, "item": item}, strict=self.strict)
                if item_template
                else _string_or_empty(item)
                for item in values
            ]
            return [value for value in rendered if value.strip()]

        if "field" in part:
            value = _get_value(context, str(part["field"]))
            rendered = _string_or_empty(value)
        elif "template" in part:
            rendered = _render_template(str(part["template"]), context, strict=self.strict)
        elif "text" in part:
            rendered = _string_or_empty(part.get("text"))
        else:
            raise TemplateRenderError("title part must define field, template, text, or list")

        prefix = _string_or_empty(part.get("prefix"))
        suffix = _string_or_empty(part.get("suffix"))
        rendered = f"{prefix}{rendered}{suffix}".strip()
        return [rendered] if rendered else []


class TemplateDescriptionGenerator:
    """Render a description from a structured ``blocks`` spec."""

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict

    def generate(self, spec: Spec, context: Context) -> str:
        newline = str(spec.get("newline", "\n"))
        char_limit = _to_int(spec.get("char_limit"), default=0)
        blocks = spec.get("blocks", [])
        if not isinstance(blocks, list):
            raise TemplateRenderError("description.blocks must be a list")

        lines: list[str] = []
        for raw_block in blocks:
            if not isinstance(raw_block, Mapping):
                raise TemplateRenderError("description block must be an object")
            if not _condition_matches(raw_block.get("when"), context):
                continue
            lines.extend(self._render_block(raw_block, context))

        description = newline.join(lines).rstrip()
        if char_limit and len(description) > char_limit:
            description = _truncate(description, char_limit)
        return description

    def _render_block(self, block: Spec, context: Context) -> list[str]:
        block_type = str(block.get("type", "line"))
        if block_type == "blank":
            return [""]
        if block_type == "line":
            return [self._render_line(block, context)]
        if block_type == "lines":
            result: list[str] = []
            raw_lines = block.get("items", [])
            if not isinstance(raw_lines, list):
                raise TemplateRenderError("lines.items must be a list")
            for raw_line in raw_lines:
                if isinstance(raw_line, Mapping):
                    if _condition_matches(raw_line.get("when"), context):
                        result.append(self._render_line(raw_line, context))
                else:
                    result.append(_render_template(str(raw_line), context, strict=self.strict))
            return result
        if block_type == "section":
            return self._render_section(block, context)
        raise TemplateRenderError(f"Unknown description block type: {block_type}")

    def _render_line(self, line: Spec, context: Context) -> str:
        if "field" in line:
            rendered = _string_or_empty(_get_value(context, str(line["field"])))
        elif "template" in line:
            rendered = _render_template(str(line["template"]), context, strict=self.strict)
        else:
            rendered = _string_or_empty(line.get("text"))

        prefix = _string_or_empty(line.get("prefix"))
        suffix = _string_or_empty(line.get("suffix"))
        return f"{prefix}{rendered}{suffix}"

    def _render_section(self, block: Spec, context: Context) -> list[str]:
        values = _as_list(_get_value(context, str(block.get("items", ""))))
        limit = _to_int(block.get("limit"), default=0)
        if limit > 0:
            values = values[:limit]
        values = [_string_or_empty(value) for value in values if _string_or_empty(value).strip()]
        if not values:
            return []

        joiner = str(block.get("join", ", "))
        result: list[str] = []
        title = _string_or_empty(block.get("title"))
        if title:
            result.append(_render_template(title, context, strict=self.strict))
        result.append(joiner.join(values))
        if block.get("trailing_blank", False):
            result.append("")
        return result


def _render_template(template: str, context: Context, *, strict: bool) -> str:
    try:
        return template.format_map(_FormatContext(context, strict=strict))
    except TemplateRenderError:
        raise
    except Exception as exc:
        raise TemplateRenderError(f"Failed to render template {template!r}: {exc}") from exc


def _condition_matches(condition: Any, context: Context) -> bool:
    if condition is None:
        return True
    if not isinstance(condition, Mapping):
        raise TemplateRenderError("condition must be an object")

    if "truthy" in condition:
        return bool(_get_value(context, str(condition["truthy"])))
    if "falsy" in condition:
        return not bool(_get_value(context, str(condition["falsy"])))
    if "and" in condition:
        return all(_condition_matches(item, context) for item in _as_list(condition["and"]))
    if "or" in condition:
        return any(_condition_matches(item, context) for item in _as_list(condition["or"]))
    if "not" in condition:
        return not _condition_matches(condition["not"], context)

    for op in ("gt", "gte", "lt", "lte", "eq", "neq", "contains"):
        if op in condition:
            operands = _as_list(condition[op])
            if len(operands) != 2:
                raise TemplateRenderError(f"condition {op} expects two operands")
            actual = _get_value(context, str(operands[0]))
            expected = operands[1]
            return _compare(op, actual, expected)

    raise TemplateRenderError(f"Unknown condition: {condition}")


def _compare(op: str, actual: Any, expected: Any) -> bool:
    try:
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
        if op == "eq":
            return actual == expected
        if op == "neq":
            return actual != expected
        if op == "contains":
            return expected in actual if actual is not None else False
    except (TypeError, ValueError):
        return False
    raise TemplateRenderError(f"Unknown comparison operator: {op}")


def _get_value(context: Context, path: str) -> Any:
    if not path:
        return ""
    current: Any = context
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part, "")
        else:
            current = getattr(current, part, "")
    return current


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."
