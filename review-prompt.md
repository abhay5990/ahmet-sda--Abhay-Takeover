# Content Template Builder - Architecture & Code Review Prompt

## Context & Goal

I'm building a **Content Template Builder** for an e-commerce game account selling platform. Users create title/description templates with `{field_name}` placeholders (e.g. `R6 Account | Level {level} | {current_rank} | {black_ice_count} Black Ice`). When posting a game account to marketplaces, the system renders templates by substituting placeholders with actual account data.

The system supports 13 different games (R6, Fortnite, Valorant, CS2, Roblox, etc.), each with its own resolved account model. Templates are stored per game + marketplace + type (title/description).

**I want you to review this entire system from every angle:** architecture, code quality, security, performance, extensibility, edge cases, naming, DRY violations, error handling, and anything else you notice. Do NOT limit your scope — I want brutal, honest feedback. If something is good, say so. If something is bad, explain why and suggest better approaches.

---

## System Architecture

```
ContentTemplate (Django model)
    |
    v
PostingDefault.title_template / description_template (FK selection)
    |
    v
adapter.prepare(title_templates={...}, description_templates={...})
    |
    v
PipelineRequest.context[TITLE_TEMPLATES] / [DESCRIPTION_TEMPLATES]
    |
    v
Composer checks context keys:
  - Both set → full template path
  - One set → hybrid (template + legacy)
  - None set → full legacy path (default)
    |
    v
compose_with_templates() → SimpleTemplateRenderer.render()
```

---

## File 1: SimpleTemplateRenderer (`renderer.py`)

```python
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
```

---

## File 2: Template Validation (`validation.py`)

```python
"""Validation for content template bodies.

Validates plain-text templates with ``{field_name}`` placeholders.
Structural checks (brace balance) live in ``renderer.py``; this module
adds field-level validation when the available field set is known.
"""

from __future__ import annotations

from typing import Any

from .renderer import TemplateRenderError, validate_template_body


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
```

---

## File 3: Compose Helper (`compose.py`)

```python
"""Generic template-based content composition.

Provides ``compose_with_templates`` that any game composer can call to
render title/description from user-created templates.  Falls back to
``None`` for marketplaces without a template, so the caller can mix
template output with legacy generators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .renderer import SimpleTemplateRenderer


@dataclass(slots=True)
class TemplateComposeResult:
    """Result of template-based content generation."""

    default_title: str | None = None
    default_description: str | None = None
    marketplace_titles: dict[str, str] = field(default_factory=dict)
    marketplace_descriptions: dict[str, str] = field(default_factory=dict)


def compose_with_templates(
    context: dict[str, Any],
    *,
    title_templates: dict[str, str] | None = None,
    description_templates: dict[str, str] | None = None,
    default_marketplace: str = "eldorado",
) -> TemplateComposeResult:
    """Render all marketplace templates and return structured results.

    Parameters:
        context: Flat field→value dict from the resolved account model.
        title_templates: Marketplace→template body mapping for titles.
        description_templates: Same for descriptions.
        default_marketplace: Which marketplace template to use as the
            default title/description (typically the first marketplace
            in the posting job).

    Returns:
        A ``TemplateComposeResult`` with rendered strings per marketplace.
        Fields are ``None`` when no template was provided for that slot.
    """
    renderer = SimpleTemplateRenderer()
    result = TemplateComposeResult()

    if title_templates:
        for marketplace, body in title_templates.items():
            rendered = renderer.render(body, context)
            result.marketplace_titles[marketplace] = rendered
        if default_marketplace in result.marketplace_titles:
            result.default_title = result.marketplace_titles[default_marketplace]
        elif result.marketplace_titles:
            result.default_title = next(iter(result.marketplace_titles.values()))

    if description_templates:
        for marketplace, body in description_templates.items():
            rendered = renderer.render(body, context)
            result.marketplace_descriptions[marketplace] = rendered
        if default_marketplace in result.marketplace_descriptions:
            result.default_description = result.marketplace_descriptions[default_marketplace]
        elif result.marketplace_descriptions:
            result.default_description = next(iter(result.marketplace_descriptions.values()))

    return result


def compose_listing_draft(
    context: dict[str, Any],
    *,
    title_templates: dict[str, str] | None,
    description_templates: dict[str, str] | None,
    media: MediaBundle,
    tags: list[str],
) -> ListingDraft:
    """Render templates and build a ListingDraft in one step.

    Shared helper that eliminates the identical compose→override→draft
    boilerplate in every game's template_content.py.
    """
    result = compose_with_templates(
        context,
        title_templates=title_templates,
        description_templates=description_templates,
    )

    overrides: dict[str, MarketplaceListingOverride] = {}
    all_marketplaces = set(result.marketplace_titles) | set(result.marketplace_descriptions)
    for mp in all_marketplaces:
        title = result.marketplace_titles.get(mp)
        desc = result.marketplace_descriptions.get(mp)
        if title is not None or desc is not None:
            overrides[mp] = MarketplaceListingOverride(title=title, description=desc)

    return ListingDraft(
        default=ListingContent(
            title=result.default_title or "",
            description=result.default_description or "",
            tags=tags,
        ),
        media=media,
        marketplace_overrides=overrides,
    )
```

---

## File 4: Field Registry (`field_registry.py`)

```python
"""Public API for template field metadata and sample context.

Consumers (e.g. the Django template editor) import only these functions.
All introspection of resolved models stays encapsulated here.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import is_dataclass
from functools import lru_cache
from typing import Any, get_type_hints

from ..core.contracts import FieldMeta, ResolvedAccountBase
from ..core.enums import ListingCategory

logger = logging.getLogger(__name__)

# Module-level cached registry to avoid rebuilding on every call.
_default_registry = None


def get_field_registry(
    game_slug: str,
    category: str = "account",
) -> list[dict[str, Any]]:
    """Return field metadata for the template editor UI.

    Each entry contains ``name``, ``placeholder``, ``description``,
    ``sample``, and ``source`` keys.
    """
    model = _resolve_model(game_slug, category)
    result: list[dict[str, Any]] = []

    for name, meta in model.FIELD_META.items():
        result.append(_meta_to_dict(name, meta))

    for name, meta in model.COMPUTED_FIELDS.items():
        result.append(_meta_to_dict(name, meta))

    return result


def get_available_fields(
    game_slug: str,
    category: str = "account",
) -> set[str]:
    """Return the set of valid field names for a game model.

    Used by validation to check template placeholders.
    """
    model = _resolve_model(game_slug, category)
    return set(model.FIELD_META) | set(model.COMPUTED_FIELDS)


def get_sample_context(
    game_slug: str,
    category: str = "account",
) -> dict[str, Any]:
    """Return a sample context dict suitable for template preview rendering."""
    model = _resolve_model(game_slug, category)
    context: dict[str, Any] = {
        name: meta.sample for name, meta in model.FIELD_META.items()
    }
    context.update({
        name: meta.sample for name, meta in model.COMPUTED_FIELDS.items()
    })
    return context


def get_resolved_model_name(
    game_slug: str,
    category: str = "account",
) -> str:
    """Return the resolved model class name (e.g. ``'RobloxResolvedAccount'``)."""
    model = _resolve_model(game_slug, category)
    return model.__name__


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _meta_to_dict(name: str, meta: FieldMeta) -> dict[str, Any]:
    return {
        "name": name,
        "placeholder": "{" + name + "}",
        "description": meta.description,
        "sample": _format_sample(meta.sample),
        "source": meta.source,
    }


def _format_sample(value: Any) -> str:
    """Convert a sample value to a human-readable display string."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value[:5])
    return str(value)


def _get_default_registry():
    """Return a cached pipeline registry instance."""
    global _default_registry
    if _default_registry is None:
        from .. import build_default_registry
        _default_registry = build_default_registry()
    return _default_registry


@lru_cache(maxsize=64)
def _resolve_model(
    game_slug: str,
    category: str = "account",
) -> type[ResolvedAccountBase]:
    """Look up the resolved model class for a game slug.

    Uses the pipeline registry to find the resolver, then inspects
    return-type annotations or sibling ``models`` module.
    Falls back to ``ResolvedAccountBase`` when resolution fails.
    """
    if not game_slug:
        return ResolvedAccountBase

    try:
        registry = _get_default_registry()
        listing_category = _to_listing_category(category)
        definition = registry.get_game(game_slug, listing_category)
    except (KeyError, ValueError) as exc:
        logger.warning("Failed to resolve model for %s/%s: %s", game_slug, category, exc)
        return ResolvedAccountBase
    except ImportError as exc:
        logger.error("Import error resolving model for %s: %s", game_slug, exc)
        return ResolvedAccountBase

    model = _model_from_resolver_return_type(definition.resolver)
    if model is not None:
        return model

    model = _model_from_resolver_module(definition.resolver.__class__.__module__)
    if model is not None:
        return model

    logger.warning("Could not find resolved model for %s/%s, using base", game_slug, category)
    return ResolvedAccountBase


def _to_listing_category(value: str) -> ListingCategory:
    try:
        return ListingCategory(value or "account")
    except ValueError:
        return ListingCategory.ACCOUNT


def _model_from_resolver_return_type(resolver: Any) -> type[ResolvedAccountBase] | None:
    try:
        return_type = get_type_hints(resolver.resolve).get("return")
    except (TypeError, AttributeError, NameError):
        return None
    return return_type if _is_resolved_model(return_type) else None


def _model_from_resolver_module(module_name: str) -> type[ResolvedAccountBase] | None:
    package = module_name.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(f"{package}.models")
    except ImportError:
        return None

    for _, cls in inspect.getmembers(module, inspect.isclass):
        if _is_resolved_model(cls):
            return cls
    return None


def _is_resolved_model(value: Any) -> bool:
    return (
        inspect.isclass(value)
        and value is not ResolvedAccountBase
        and issubclass(value, ResolvedAccountBase)
        and is_dataclass(value)
    )
```

---

## File 5: Context Keys (`context_keys.py`)

```python
"""Typed constants for PipelineRequest.context keys.

Centralizes all known context keys to avoid scattered string literals
and make usage discoverable via IDE autocomplete.

Each key is a ``ContextKey[T]`` that subclasses ``str``, so it works
everywhere a plain string key would (dict literals, ``**`` unpacking,
``request.context.get(ctx.KEY)``).  The generic parameter ``T`` carries
the expected value type for static analysis.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar, overload

T = TypeVar("T")


class ContextKey(str, Generic[T]):
    """A str-subclass that also carries the expected value type as ``T``."""

    def __new__(cls, key: str) -> ContextKey[T]:
        return str.__new__(cls, key)

    @overload
    def get(self, request: Any) -> T | None: ...

    @overload
    def get(self, request: Any, default: T) -> T: ...

    def get(self, request: Any, default: T | None = None) -> T | None:
        return request.context.get(self, default)

    def set(self, request: Any, value: T) -> None:
        request.context[self] = value


# -- Content template rendering -----------------------------------------------
TITLE_TEMPLATES: ContextKey[dict[str, str]] = ContextKey("title_templates")
DESCRIPTION_TEMPLATES: ContextKey[dict[str, str]] = ContextKey("description_templates")
```

---

## File 6: Core Contracts (relevant parts from `contracts.py`)

```python
@dataclass(frozen=True, slots=True)
class FieldMeta:
    """Metadata for a single template-visible field."""
    description: str
    sample: Any
    source: str = "resolved"


@dataclass(slots=True)
class ResolvedAccountBase:
    """Common fields shared by all resolved game account models."""
    item_id: str = ""
    category_id: int = 0
    price: float = 0.0
    kind: Literal["stock", "dropshipping"] = "stock"
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        "item_id": FieldMeta("Source item ID.", "sample-item-123"),
        "category_id": FieldMeta("Listing category ID.", 1),
        "price": FieldMeta("Listing price.", 10.0),
        "kind": FieldMeta("Listing kind: stock or dropshipping.", "stock"),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        "album_url": FieldMeta("Hosted media album URL when available.", "https://imgur.com/a/sample", "runtime"),
        "is_stock": FieldMeta("True for stock listings.", True, "runtime"),
    }


@dataclass(slots=True)
class ListingDraft:
    """Platform-independent listing draft with optional marketplace overrides."""
    default: ListingContent = field(default_factory=ListingContent)
    media: MediaBundle = field(default_factory=MediaBundle)
    marketplace_overrides: dict[str, MarketplaceListingOverride] = field(default_factory=dict)

    def content_for(self, marketplace: str) -> ListingContent:
        """Return the effective listing content for the requested marketplace."""
        override = self.marketplace_overrides.get(marketplace.lower())
        if override is None:
            return ListingContent(
                title=self.default.title,
                description=self.default.description,
                tags=list(self.default.tags),
            )
        return ListingContent(
            title=override.title if override.title is not None else self.default.title,
            description=override.description if override.description is not None else self.default.description,
            tags=list(override.tags) if override.tags is not None else list(self.default.tags),
        )


class ListingComposer(Protocol[TSubject]):
    """Build listing content from a resolved subject."""
    def compose(self, subject: TSubject, request: PipelineRequest, media: MediaBundle) -> ListingDraft: ...
```

---

## File 7: Example Game Model (`R6ResolvedAccount`)

```python
@dataclass(slots=True)
class R6ResolvedAccount(ResolvedAccountBase):
    tracker_url: str = ""
    level: int = 0
    current_rank: str = "Unranked"
    peak_rank: str = "Unranked"
    operators: list[str] = field(default_factory=list)
    operator_count: int = 0
    skin_count: int = 0
    black_ice_count: int = 0
    inventory: R6InventoryBreakdown = field(default_factory=R6InventoryBreakdown)
    psn_connected: bool = False
    xbox_connected: bool = False

    @property
    def ranked_ready(self) -> bool:
        return self.level >= 50

    @property
    def available_platforms(self) -> list[str]:
        platforms = ["PC"]
        if self.psn_connected: platforms.append("PlayStation")
        if self.xbox_connected: platforms.append("Xbox")
        return platforms

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "level": FieldMeta("Account level.", 120),
        "current_rank": FieldMeta("Current ranked season rank.", "Platinum"),
        "peak_rank": FieldMeta("Highest achieved rank.", "Diamond"),
        "operators": FieldMeta("Unlocked operator names.", ["Ash", "Jager", "Mira"]),
        "operator_count": FieldMeta("Unlocked operator count.", 45),
        "skin_count": FieldMeta("Total skin count.", 150),
        "black_ice_count": FieldMeta("Black Ice skin count.", 12),
        # ... etc
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "ranked_ready": FieldMeta("Level 50+ for ranked play.", True, "computed"),
        "available_platforms": FieldMeta("Connected platform list.", ["PC"], "computed"),
        # ... etc
    }
```

---

## File 8: Template Content Generator (R6 example — `template_content.py`)

```python
class R6TemplateContentGenerator:
    """Compose R6 listing content using user-created templates."""

    def compose(
        self,
        account: R6ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        return compose_listing_draft(
            build_r6_context(account, request, media),
            title_templates=ctx.TITLE_TEMPLATES.get(request),
            description_templates=ctx.DESCRIPTION_TEMPLATES.get(request),
            media=media,
            tags=["r6", "rainbow-six", "account"],
        )


def build_r6_context(account: R6ResolvedAccount, request: PipelineRequest, media: MediaBundle) -> dict[str, Any]:
    skip = {"credentials", "inventory"}
    context: dict[str, Any] = {
        field.name: getattr(account, field.name)
        for field in dc_fields(account)
        if field.name not in skip
    }

    inv = account.inventory
    context.update({
        "glacier_count": inv.glaciers.count,
        "glacier_items": inv.glaciers.items,
        "black_ice_count": inv.black_ices.count,
        "black_ice_items": inv.black_ices.items,
        # ... many more inventory fields
        "ranked_ready": account.ranked_ready,
        "available_platforms": account.available_platforms,
        "linkable_platforms": account.linkable_platforms,
        "ownership_text": account.ownership_text,
        "platform_type_text": account.platform_type_text,
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })

    return context
```

**The `compose()` method is now DRY** — Fortnite and Roblox use the exact same 6-line pattern (via `compose_listing_draft()`), with only their own `build_X_context()` functions differing. 10 more games still need a `template_content.py` with this pattern.

---

## File 9: Composer with Hybrid Path (R6 example — `composer.py`)

```python
class R6Composer:
    def __init__(self) -> None:
        self.title_generator = R6ResolvedTitleGenerator()
        self.description_generator = R6ResolvedDescriptionGenerator()
        self.template_content_generator = R6TemplateContentGenerator()

    def compose(self, account: R6ResolvedAccount, request: PipelineRequest, media: MediaBundle) -> ListingDraft:
        has_title_templates = bool(ctx.TITLE_TEMPLATES.get(request))
        has_desc_templates = bool(ctx.DESCRIPTION_TEMPLATES.get(request))

        # Full template path — both title and description from templates
        if has_title_templates and has_desc_templates:
            return self.template_content_generator.compose(account, request, media)

        # Legacy path (default)
        title = self.title_generator.generate(account, site="default")
        g2g_title = self.title_generator.generate(account, site="g2g")
        description = self.description_generator.generate(account, media=media, site="default")

        draft = ListingDraft(
            default=ListingContent(title=title, description=description, tags=["r6", "rainbow-six", "account"]),
            media=media,
            marketplace_overrides={"g2g": MarketplaceListingOverride(title=g2g_title)},
        )

        # Partial template override — only title OR only description
        if has_title_templates or has_desc_templates:
            template_draft = self.template_content_generator.compose(account, request, media)
            if has_title_templates:
                draft.default.title = template_draft.default.title
                for mp, override in template_draft.marketplace_overrides.items():
                    if override.title is not None:
                        existing = draft.marketplace_overrides.get(mp)
                        if existing:
                            existing.title = override.title
                        else:
                            draft.marketplace_overrides[mp] = MarketplaceListingOverride(title=override.title)
            if has_desc_templates:
                draft.default.description = template_draft.default.description
                for mp, override in template_draft.marketplace_overrides.items():
                    if override.description is not None:
                        existing = draft.marketplace_overrides.get(mp)
                        if existing:
                            existing.description = override.description
                        else:
                            draft.marketplace_overrides[mp] = MarketplaceListingOverride(description=override.description)

        return draft
```

**This exact hybrid pattern is copy-pasted in R6, Fortnite, and Roblox composers.** 10 more games still need it.

---

## File 10: Django ContentTemplate Model

```python
class ContentTemplate(models.Model):
    TEMPLATE_TYPE_CHOICES = [('title', 'Title'), ('description', 'Description')]
    MARKETPLACE_CHOICES = [
        ('eldorado', 'Eldorado'), ('gameboost', 'GameBoost'),
        ('g2g', 'G2G'), ('playerauctions', 'PlayerAuctions'),
    ]

    game = models.ForeignKey('inventory.Game', on_delete=models.CASCADE, related_name='content_templates')
    marketplace = models.CharField(max_length=30, choices=MARKETPLACE_CHOICES)
    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPE_CHOICES)
    name = models.CharField(max_length=100)
    body = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_templates'
        constraints = [
            models.UniqueConstraint(fields=['game', 'marketplace', 'name', 'template_type'], name='unique_content_template'),
        ]
        indexes = [
            models.Index(fields=['game', 'marketplace', 'template_type'], name='content_template_lookup_idx'),
        ]

    def clean(self):
        super().clean()
        from payload_pipeline.content_templates import TemplateValidationError, validate_template
        try:
            validate_template(self.body, template_type=self.template_type)
        except TemplateValidationError as exc:
            raise ValidationError({'body': str(exc)}) from exc
```

---

## File 11: API Endpoints (`api/content_templates.py`)

```python
@role_required('admin', 'user')
@require_GET
def list_content_templates(request):
    game_id = request.GET.get('game_id')
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)
    qs = ContentTemplate.objects.filter(game_id=game_id)
    marketplace = request.GET.get('marketplace')
    if marketplace:
        qs = qs.filter(marketplace=marketplace)
    template_type = request.GET.get('template_type')
    if template_type:
        qs = qs.filter(template_type=template_type)
    return JsonResponse({'templates': [_serialize(t) for t in qs]})


@role_required('admin', 'user')
@require_POST
def create_content_template(request):
    body = _parse_json(request)
    if isinstance(body, JsonResponse): return body
    game_id = body.get('game_id')
    marketplace = body.get('marketplace')
    template_type = body.get('template_type')
    name = body.get('name', '').strip()
    template_body = body.get('body', '')
    if not all([game_id, marketplace, template_type, name, template_body]):
        return JsonResponse({'error': 'game_id, marketplace, template_type, name, and body are required'}, status=400)
    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)
    game_slug = game.slug if game else ''
    available = get_available_fields(game_slug) if game_slug else None
    warnings = _validate_body(template_body, template_type, available)
    if isinstance(warnings, JsonResponse): return warnings
    template = ContentTemplate(game=game, marketplace=marketplace, template_type=template_type, name=name, body=template_body)
    try:
        template.full_clean()
        template.save()
    except ValidationError as exc:
        return JsonResponse({'error': _validation_message(exc)}, status=400)
    return JsonResponse({'ok': True, 'template': _serialize(template), 'warnings': warnings})


@role_required('admin', 'user')
@require_http_methods(['POST', 'DELETE'])
def content_template_detail(request, template_id: int):
    try:
        template = ContentTemplate.objects.get(id=template_id)
    except ContentTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)
    if request.method == 'DELETE':
        template.delete()
        return JsonResponse({'ok': True})
    body = _parse_json(request)
    if isinstance(body, JsonResponse): return body
    name = body.get('name', '').strip()
    template_body = body.get('body', '')
    if not name or not template_body:
        return JsonResponse({'error': 'name and body are required'}, status=400)
    game_slug = template.game.slug if template.game else ''
    available = get_available_fields(game_slug) if game_slug else None
    warnings = _validate_body(template_body, template.template_type, available)
    if isinstance(warnings, JsonResponse): return warnings
    template.name = name
    template.body = template_body
    try:
        template.full_clean()
        template.save()
    except ValidationError as exc:
        return JsonResponse({'error': _validation_message(exc)}, status=400)
    return JsonResponse({'ok': True, 'template': _serialize(template), 'warnings': warnings})


@role_required('admin', 'user')
@require_POST
def preview_content_template(request):
    body = _parse_json(request)
    if isinstance(body, JsonResponse): return body
    template_body = body.get('body', '')
    template_type = body.get('template_type', '')
    game_id = body.get('game_id')
    if not template_body:
        return JsonResponse({'error': 'body is required'}, status=400)
    game_slug = _game_slug(game_id)
    available = get_available_fields(game_slug) if game_slug else None
    warnings = _validate_body(template_body, template_type, available)
    if isinstance(warnings, JsonResponse): return warnings
    context = get_sample_context(game_slug, 'account')
    try:
        renderer = SimpleTemplateRenderer()
        rendered = renderer.render(template_body, context)
    except TemplateRenderError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'rendered': rendered, 'warnings': warnings, 'context': context})
```

---

## File 12: Orchestrator Integration (stock posting flow)

```python
class StockOrchestrator:
    def __init__(self):
        self._title_templates: dict[str, str] | None = None
        self._description_templates: dict[str, str] | None = None

    def _load_templates(self, game_id: int) -> None:
        defaults = {
            d.marketplace: d
            for d in PostingDefault.objects.filter(
                game_id=game_id,
            ).select_related('title_template', 'description_template')
        }
        self._title_templates, self._description_templates = (
            load_templates_for_posting(game_id=game_id, posting_defaults=defaults)
        )

    def execute(self, job):
        self._load_templates(job.game_id)
        # ... then in _prepare_once():

    def _prepare_once(self, ...):
        prepare_result = adapter.prepare(
            game_slug=job.game.slug,
            sources=sources,
            kind=ListingKind.STOCK,
            title_templates=self._title_templates,
            description_templates=self._description_templates,
        )
```

`load_templates_for_posting()`:
```python
def load_templates_for_posting(*, game_id, posting_defaults):
    title_templates, description_templates = {}, {}
    for marketplace, defaults in posting_defaults.items():
        if hasattr(defaults, 'title_template') and defaults.title_template_id:
            title_templates[marketplace] = defaults.title_template.body
        if hasattr(defaults, 'description_template') and defaults.description_template_id:
            description_templates[marketplace] = defaults.description_template.body
    return (title_templates or None, description_templates or None)
```

---

## File 13: PipelineRequest Factory (`request.py`)

```python
def build_request(*, game_slug, sources, kind, disable_media=True, lzt_image_fetcher=None,
                  title_templates=None, description_templates=None) -> PipelineRequest:
    ctx = {ctx_keys.DISABLE_MEDIA: disable_media}
    if lzt_image_fetcher is not None:
        ctx[ctx_keys.LZT_IMAGE_FETCHER] = lzt_image_fetcher
    if title_templates:
        ctx[ctx_keys.TITLE_TEMPLATES] = title_templates
    if description_templates:
        ctx[ctx_keys.DESCRIPTION_TEMPLATES] = description_templates
    return PipelineRequest(game=game_slug, category=ListingCategory.ACCOUNT, kind=kind, sources=sources, context=ctx)
```

---

## File 14: Frontend (`content_templates.html`)

Alpine.js + Tailwind CSS single-page template editor with:
- Game/marketplace/type filter dropdowns
- Card-based template list with preview/edit/delete
- Create/edit modal with field palette (click to insert `{field}` at cursor)
- Preview button (renders with sample data from API)
- CRUD via fetch to Django API endpoints

```html
<!-- See full HTML source above — Alpine.js component with CRUD operations -->
```

---

## What I Want You To Review

Please analyze everything above and provide feedback on:

1. **Architecture & Design** — Is the layering clean? Is the separation of concerns right? Is the data flow between Django and the pipeline library well-designed? Any coupling issues?

2. **Code Quality & DRY** — The `*TemplateContentGenerator.compose()` boilerplate has been DRY-refactored into `compose_listing_draft()` (all 3 existing games now use the same 6-line pattern). The **hybrid path in each game's `Composer.compose()`** (full template / partial template / legacy fallback) is still copy-pasted 3 times (soon 13 times). Is the hybrid path worth a shared base class or mixin, or is the copy-paste acceptable?

3. **Security** — Is the regex-based renderer truly safe? Any XSS risks in the frontend? CSRF handling? API authorization gaps?

4. **Performance** — N+1 queries? Unnecessary work? Caching opportunities? Template rendering costs at scale?

5. **Error Handling** — Edge cases not covered? Silent failures? Missing validation?

6. **Naming & API Design** — Inconsistent naming? Confusing parameter names? Unclear contracts?

7. **Extensibility** — How hard will it be to add modifier syntax (`{field | limit:10}`)? What about multi-language support? Template versioning?

8. **Frontend** — UX issues? Missing features? Alpine.js patterns that could be improved?

9. **Testing** — What should be tested? What are the riskiest paths?

10. **Anything else** — Anything I'm missing or doing wrong?

Be specific. Reference file names and line numbers. Suggest concrete improvements with code examples where applicable.
