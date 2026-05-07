"""Template-backed content rendering helpers for payload_pipeline.

This package is intentionally independent from game slices.  Game-specific
adapters should prepare a flat context dict; these renderers only know how to
turn that context into title parts and description blocks.
"""

from .renderer import (
    TemplateDescriptionGenerator,
    TemplateRenderError,
    TemplateTitleGenerator,
)
from .manager import TemplateManager
from .providers import (
    DictTemplateProvider,
    DictTemplateOverrideProvider,
    JsonFileTemplateProvider,
    JsonFileTemplateOverrideProvider,
    TemplateOverrideProvider,
    TemplateProvider,
    merge_template_maps,
)
from .validation import TemplateValidationError, validate_template_map

__all__ = [
    "DictTemplateProvider",
    "DictTemplateOverrideProvider",
    "JsonFileTemplateProvider",
    "JsonFileTemplateOverrideProvider",
    "TemplateDescriptionGenerator",
    "TemplateManager",
    "TemplateOverrideProvider",
    "TemplateProvider",
    "TemplateRenderError",
    "TemplateTitleGenerator",
    "TemplateValidationError",
    "merge_template_maps",
    "validate_template_map",
]
