"""Simple template renderer for listing content.

Renders plain-text templates with ``{field_name}`` placeholders against a
flat context dict built from the resolved account model.

The renderer is intentionally simple — no nested logic, no JSON specs.
Future modifier support (``{field | limit:10}``) will be added via the
``_resolve_placeholder`` extension point.

Security note: uses regex-based placeholder extraction instead of
``str.format_map`` to prevent Python attribute traversal attacks
(e.g. ``{field.__class__}``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


Context = Mapping[str, Any]

# Matches {field_name} — alphanumeric + underscores only (no dots, no dunders).
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Matches any {…} block (for detecting invalid placeholder syntax after brace balance check).
_ANY_BRACE_RE = re.compile(r"\{[^{}]*\}")


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

    def render(self, template: str, context: Context) -> str:
        """Render *template* by substituting placeholders from *context*."""
        if not template:
            return ""

        def _replace(match: re.Match[str]) -> str:
            field_name = match.group(1)
            return self._resolve_placeholder(field_name, context)

        return _PLACEHOLDER_RE.sub(_replace, template)

    def extract_fields(self, template: str) -> list[str]:
        """Return the list of unique field names referenced in *template*."""
        seen: set[str] = set()
        result: list[str] = []
        for match in _PLACEHOLDER_RE.finditer(template):
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def _resolve_placeholder(self, field_name: str, context: Context) -> str:
        """Resolve a single placeholder to its string value.

        Extension point for future modifier support.
        """
        if field_name not in context:
            if self.strict:
                raise TemplateRenderError(f"Missing template field: {field_name}")
            return ""

        value = context[field_name]
        return _format_value(value)


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
    renderer = SimpleTemplateRenderer()
    fields = renderer.extract_fields(body)

    if available_fields is not None:
        for field_name in fields:
            if field_name not in available_fields:
                warnings.append(f"Unknown field: {field_name}")

    # Check for malformed placeholders (unclosed braces, nested braces)
    _check_brace_balance(body)

    # Check for {…} blocks that look like placeholders but aren't valid identifiers.
    # e.g. {bad-field}, {123abc}, { space } — these pass brace balance but silently
    # render as literal text, which is almost certainly a user typo.
    for match in _ANY_BRACE_RE.finditer(body):
        block = match.group()
        if not _PLACEHOLDER_RE.fullmatch(block):
            raise TemplateRenderError(
                f"Invalid placeholder syntax: {block!r} — "
                "use {field_name} with letters, digits, and underscores only"
            )

    return warnings


def _check_brace_balance(body: str) -> None:
    """Raise if the template has unbalanced or nested braces."""
    depth = 0
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
            if depth > 1:
                raise TemplateRenderError(
                    f"Nested braces are not supported (position {i})"
                )
        elif ch == "}":
            if depth == 0:
                raise TemplateRenderError(
                    f"Unexpected closing brace (position {i})"
                )
            depth -= 1
    if depth > 0:
        raise TemplateRenderError("Unclosed brace in template")
