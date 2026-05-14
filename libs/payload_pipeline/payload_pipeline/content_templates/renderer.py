"""Simple template renderer for listing content.

Renders plain-text templates with ``{field_name}`` placeholders against a
flat context dict built from the resolved account model.

Now uses an AST-based parser internally for placeholder substitution,
modifier chains, and conditional blocks.

Security note: uses regex-based field name validation instead of
``str.format_map`` to prevent Python attribute traversal attacks
(e.g. ``{field.__class__}``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ast_nodes import IfBlockNode, Node, PlaceholderNode, TextNode
from .modifiers import apply_modifier_chain
from .parser import TemplateParseError, parse


Context = Mapping[str, Any]


class TemplateRenderError(ValueError):
    """Raised when a template cannot be rendered."""


class SimpleTemplateRenderer:
    """Render a plain-text template string with ``{field}`` placeholders.

    Usage::

        renderer = SimpleTemplateRenderer()
        title = renderer.render(
            "Level {level} | {rank} | {game_name} Account",
            {"level": 45, "rank": "Diamond", "game_name": "Valorant"},
        )
        # => "Level 45 | Diamond | Valorant Account"

    Missing fields resolve to ``""`` by default (strict mode raises).
    List values are comma-joined automatically.
    """

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict

    def render(
        self,
        template: str,
        context: Context,
        *,
        max_length: int = 0,
        separator: str = " | ",
        pin_last: int = 0,
    ) -> str:
        """Render *template* by substituting placeholders from *context*.

        When *max_length* is set (> 0), the rendered output is split by
        *separator* into segments and reassembled keeping only as many
        complete segments as fit within the character limit.

        When *pin_last* is set (> 0), the last N non-empty segments are
        always kept and the middle segments are truncated instead.
        """
        if not template:
            return ""
        nodes = parse(template)
        rendered = self._render_nodes(nodes, context)
        if max_length > 0:
            rendered = _assemble_segments(
                rendered, max_length, separator, pin_last=pin_last,
            )
        return rendered

    def extract_fields(self, template: str) -> list[str]:
        """Return the list of unique field names referenced in *template*."""
        nodes = parse(template)
        seen: set[str] = set()
        result: list[str] = []
        self._collect_fields(nodes, seen, result)
        return result

    def _render_nodes(self, nodes: tuple[Node, ...], context: Context) -> str:
        parts: list[str] = []
        for node in nodes:
            if isinstance(node, TextNode):
                parts.append(node.text)
            elif isinstance(node, PlaceholderNode):
                parts.append(self._resolve_placeholder(node, context))
            elif isinstance(node, IfBlockNode):
                if self._evaluate_condition(node.condition, context):
                    parts.append(self._render_nodes(node.if_body, context))
                else:
                    parts.append(self._render_nodes(node.else_body, context))
        return "".join(parts)

    def _resolve_placeholder(self, node: PlaceholderNode, context: Context) -> str:
        """Resolve a single placeholder to its string value.

        Extension point for future modifier support.
        """
        if node.field_name not in context:
            if self.strict:
                raise TemplateRenderError(f"Missing template field: {node.field_name}")
            return ""

        value = context[node.field_name]
        if node.modifiers:
            value = apply_modifier_chain(value, node.modifiers)
        return _format_value(value)

    def _evaluate_condition(self, cond, context: Context) -> bool:
        """Evaluate an {#if} condition against the context."""
        value = context.get(cond.field_name)

        if cond.operator == "truthy":
            return _is_truthy(value)

        if value is None:
            return cond.operator in ("!=",)

        # Try numeric comparison
        num_value = _try_numeric(value)
        num_target = _try_numeric(cond.value)

        if num_value is not None and num_target is not None:
            return _compare(num_value, cond.operator, num_target)

        # Fall back to string comparison
        str_value = str(value)
        str_target = cond.value if cond.value is not None else ""
        return _compare(str_value, cond.operator, str_target)

    def _collect_fields(
        self, nodes: tuple[Node, ...], seen: set[str], result: list[str]
    ) -> None:
        for node in nodes:
            if isinstance(node, PlaceholderNode):
                if node.field_name not in seen:
                    seen.add(node.field_name)
                    result.append(node.field_name)
            elif isinstance(node, IfBlockNode):
                if node.condition.field_name not in seen:
                    seen.add(node.condition.field_name)
                    result.append(node.condition.field_name)
                self._collect_fields(node.if_body, seen, result)
                self._collect_fields(node.else_body, seen, result)


def _assemble_segments(
    rendered: str,
    max_length: int,
    separator: str,
    *,
    pin_last: int = 0,
) -> str:
    """Keep only as many segments as fit within *max_length*.

    Splits *rendered* by *separator*, then reassembles left-to-right,
    stopping before adding a segment that would exceed the limit.
    Empty segments (from falsy conditionals) are silently dropped.

    When *pin_last* > 0, the last N non-empty segments are always
    reserved and the middle is filled with whatever fits.
    """
    segments = [s.strip() for s in rendered.split(separator) if s.strip()]

    if not segments:
        return ""

    if pin_last <= 0 or pin_last >= len(segments):
        # Simple mode: fill left-to-right
        return _fill_left_to_right(segments, max_length, separator)

    # Split into body and pinned tail
    tail = segments[-pin_last:]
    body = segments[:-pin_last]

    # Calculate reserved tail cost
    tail_cost = sum(len(s) for s in tail) + len(separator) * len(tail)

    remaining = max_length - tail_cost
    if remaining <= 0:
        # Not even tail fits — just fit what we can from everything
        return _fill_left_to_right(segments, max_length, separator)

    # Fill body left-to-right within remaining budget
    built: list[str] = []
    current_length = 0
    for segment in body:
        addition = len(segment) + (len(separator) if built else 0)
        if current_length + addition > remaining:
            break
        built.append(segment)
        current_length += addition

    built.extend(tail)
    return separator.join(built)


def _fill_left_to_right(
    segments: list[str],
    max_length: int,
    separator: str,
) -> str:
    """Fill segments left-to-right until max_length is reached."""
    built: list[str] = []
    current_length = 0

    for segment in segments:
        addition = len(segment) + (len(separator) if built else 0)
        if current_length + addition > max_length:
            break
        built.append(segment)
        current_length += addition

    return separator.join(built)


def _format_value(value: Any) -> str:
    """Convert a context value to its display string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        items = [_format_value(item) for item in value if item is not None]
        return ", ".join(items)
    return str(value)


def _is_truthy(value: Any) -> bool:
    """Truthiness rules for ``{#if field}``."""
    if value is None:
        return False
    if value == "":
        return False
    if value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
        return False
    if isinstance(value, list) and len(value) == 0:
        return False
    return True


def _try_numeric(value: Any) -> int | float | None:
    """Try to interpret a value as a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            pass
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return None


def _compare(a: Any, op: str, b: Any) -> bool:
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == "=":
        return a == b
    if op == "!=":
        return a != b
    return False


def validate_template_body(
    body: str,
    available_fields: set[str] | None = None,
) -> list[str]:
    """Validate a template body string and return a list of warnings.

    Returns an empty list if the template is valid.
    Warnings are non-fatal (e.g. unknown field names).
    Raises ``TemplateRenderError`` for structural problems.
    """
    if not body or not body.strip():
        raise TemplateRenderError("Template body cannot be empty")

    warnings: list[str] = []

    try:
        nodes = parse(body)
    except TemplateParseError as exc:
        raise TemplateRenderError(str(exc)) from exc

    if available_fields is not None:
        renderer = SimpleTemplateRenderer()
        fields = renderer.extract_fields(body)
        for field_name in fields:
            if field_name not in available_fields:
                warnings.append(f"Unknown field: {field_name}")

    return warnings
