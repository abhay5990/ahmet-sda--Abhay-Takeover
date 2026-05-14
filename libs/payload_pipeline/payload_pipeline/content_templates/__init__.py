"""Simple template rendering for listing content.

This package provides a plain-text template engine with ``{field_name}``
placeholders.  Game-specific adapters prepare a flat context dict from
their resolved models; the renderer substitutes placeholders.

Template storage and selection lives in the Django layer (ContentTemplate
model), not here.  This package only handles rendering and field metadata.
"""

from .renderer import (
    SimpleTemplateRenderer,
    TemplateRenderError,
    validate_template_body,
)
from .parser import TemplateParseError
from .modifiers import ModifierError
from .validation import TemplateValidationError, validate_template
from .field_registry import get_field_registry, get_resolved_model_name, get_sample_context
from .compose import (
    TemplateComposeResult,
    apply_template_overrides,
    compose_listing_draft,
    compose_with_templates,
)

__all__ = [
    "ModifierError",
    "SimpleTemplateRenderer",
    "TemplateComposeResult",
    "TemplateParseError",
    "TemplateRenderError",
    "TemplateValidationError",
    "apply_template_overrides",
    "compose_listing_draft",
    "compose_with_templates",
    "get_field_registry",
    "get_resolved_model_name",
    "get_sample_context",
    "validate_template",
    "validate_template_body",
]
