"""Validation for content template bodies.

Validates plain-text templates with ``{field_name}`` placeholders.
Structural checks (brace balance) live in ``renderer.py``; this module
adds field-level validation when the available field set is known.
"""

from __future__ import annotations

from typing import Any

from .renderer import TemplateRenderError, validate_template_body
from .parser import TemplateParseError


class TemplateValidationError(ValueError):
    """Raised when a content template has an invalid shape."""


def validate_template(
    body: str,
    *,
    template_type: str = "",
    available_fields: set[str] | None = None,
    max_length: int = 10_000,
) -> list[str]:
    """Validate a template body and return warnings.

    Raises ``TemplateValidationError`` for fatal issues.
    Returns a list of non-fatal warnings (e.g. unknown fields).

    Parameters:
        body: The template text with ``{field}`` placeholders.
        template_type: ``"title"`` or ``"description"`` — used for
            type-specific checks (e.g. title should be single-line).
        available_fields: Known field names for the target game model.
            If provided, unknown placeholders generate warnings.
        max_length: Maximum allowed template body length.
    """
    if not body or not body.strip():
        raise TemplateValidationError("Template body cannot be empty")

    if len(body) > max_length:
        raise TemplateValidationError(
            f"Template body exceeds maximum length ({len(body)} > {max_length})"
        )

    if template_type == "title" and "\n" in body.strip():
        raise TemplateValidationError("Title templates must be a single line")

    try:
        warnings = validate_template_body(body, available_fields)
    except TemplateRenderError as exc:
        raise TemplateValidationError(str(exc)) from exc

    return warnings
