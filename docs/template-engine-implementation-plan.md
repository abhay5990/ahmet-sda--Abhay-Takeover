# Template Engine v2 — Implementation Plan

## For the implementing AI

This document is your primary guide. Before writing any code:

1. Read this entire document to understand the full scope.
2. Read `docs/template-engine-rfc.md` (v2) for the approved design and rationale.
3. Read `docs/pipeline-flow.md` for how templates flow through the system.
4. Read the existing code files listed in each phase before modifying them.
5. If any instruction here seems architecturally wrong or not enterprise-grade, **stop and explain why** before proceeding. We want you to push back on bad decisions.

---

## Project Context

This is a Django + payload_pipeline (standalone Python lib) e-commerce system. The payload_pipeline lib lives at:

```
libs/payload_pipeline/payload_pipeline/
```

The Django app lives at:

```
backend/apps/posting/
```

The template engine code is in:

```
libs/payload_pipeline/payload_pipeline/content_templates/
    __init__.py          # Public API exports
    renderer.py          # SimpleTemplateRenderer — current {field} substitution
    validation.py        # Template body validation
    compose.py           # compose_with_templates, apply_template_overrides
    field_registry.py    # Game model introspection for field metadata
```

Tests are at:

```
libs/payload_pipeline/tests/unit/test_content_templates.py
```

The renderer is used via `compose.py` functions, which are called from game-specific composers (e.g., `games/r6/account/content/composer.py`).

---

## Current State

The renderer currently supports only `{field_name}` placeholders via a single regex:

```python
# renderer.py:25
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
```

Key file: `renderer.py` — `SimpleTemplateRenderer` class with:
- `render(template, context)` — substitute placeholders
- `extract_fields(template)` — list unique field names
- `_resolve_placeholder(field_name, context)` — extension point (docstring says "for future modifier support")
- `_format_value(value)` — None->"", bool->"Yes"/"No", list->", ".join, else str()

Key file: `validation.py` — `validate_template(body, template_type, available_fields, max_length)`
- Checks empty body, max length, single-line for titles
- Delegates brace balance to `validate_template_body()` in renderer.py

---

## Implementation Phases

### Phase 1: AST Parser + Modifier Infrastructure

**Goal:** Replace regex-based rendering with AST-based rendering. Add modifier support. All existing templates must produce identical output.

**Files to create:**

#### 1a. `content_templates/ast_nodes.py` (NEW)

Define the AST node types as frozen dataclasses:

```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class Modifier:
    name: str             # "limit", "join", "upper", etc.
    arg: str | None       # "3", "-", "N/A", etc. None if no argument.

@dataclass(frozen=True, slots=True)
class TextNode:
    text: str

@dataclass(frozen=True, slots=True)
class PlaceholderNode:
    field_name: str
    modifiers: tuple[Modifier, ...]    # Use tuple for frozen+hashable

@dataclass(frozen=True, slots=True)
class Condition:
    field_name: str
    operator: str         # "truthy", ">", ">=", "<", "<=", "=", "!="
    value: str | None     # None for truthy check

@dataclass(frozen=True, slots=True)
class IfBlockNode:
    condition: Condition
    if_body: tuple[Node, ...]      # Nodes when condition is true
    else_body: tuple[Node, ...]    # Nodes when condition is false (empty tuple if no else)

# Union type for all nodes
Node = TextNode | PlaceholderNode | IfBlockNode
```

**Important:** Use `tuple` not `list` for frozen dataclass fields.

#### 1b. `content_templates/parser.py` (NEW)

A character-by-character scanner that produces `list[Node]` from a template string.

**Parsing rules:**

1. Outside `{...}`: accumulate text into TextNode.
2. `{#if ...}`: parse condition, scan body until `{#else}` or `{/if}`, produce IfBlockNode.
3. `{#else}`: only valid inside an `{#if}` body. Switch to else_body collection.
4. `{/if}`: close the current IfBlockNode.
5. `{field}` or `{field | mod:arg | mod}`: produce PlaceholderNode with parsed modifiers.
6. Nested `{#if}` inside another `{#if}`: raise `TemplateParseError` immediately.

**Condition parsing from `{#if ...}`:**

Extract the content between `{#if ` and `}`, then parse:
- `"field"` -> Condition(field, "truthy", None)
- `"field > 5000"` -> Condition(field, ">", "5000")
- `"field >= 100"` -> Condition(field, ">=", "100")
- `"field = PC"` -> Condition(field, "=", "PC")
- `"field != dropshipping"` -> Condition(field, "!=", "dropshipping")

**Modifier parsing from `{field | mod:arg | mod2}`:**

Split by ` | ` (space-pipe-space), first segment is field name, rest are modifiers:
- `"mod"` -> Modifier("mod", None)
- `"mod:arg"` -> Modifier("mod", "arg")
- `"mod:arg with spaces"` -> Modifier("mod", "arg with spaces")

**Error handling:**
- Raise `TemplateParseError(message, position)` with character position for all structural errors.
- `TemplateParseError` should subclass `TemplateRenderError` for backward compatibility.

**Security:**
- Field names: validate against `[a-zA-Z_][a-zA-Z0-9_]*`
- Modifier names: validate against `[a-zA-Z_][a-zA-Z0-9_]*`
- Modifier args: allow `[a-zA-Z0-9_ /,.:;!?-]` (printable, no braces, no quotes, no backslash)
- Max block count: reject templates with more than 50 IfBlockNodes

**Caching:** The parser output is deterministic for a given template string. Consider `@lru_cache` on the parse function since templates are rendered many times with different contexts.

```python
@lru_cache(maxsize=256)
def parse(template: str) -> tuple[Node, ...]:
    ...
```

#### 1c. `content_templates/modifiers.py` (NEW)

Modifier registry and type-preserving execution.

```python
from __future__ import annotations
from typing import Any

class ModifierError(ValueError):
    """Raised when a modifier cannot be applied."""

def apply_modifier(value: Any, modifier_name: str, arg: str | None) -> Any:
    """Apply a single modifier to a value, returning the transformed value.

    The return type depends on the modifier — this is type-preserving.
    Final string conversion happens AFTER all modifiers via _format_value().
    """
    handler = _MODIFIER_REGISTRY.get(modifier_name)
    if handler is None:
        raise ModifierError(f"Unknown modifier: {modifier_name}")
    return handler(value, arg)

def apply_modifier_chain(value: Any, modifiers: tuple[Modifier, ...]) -> Any:
    """Apply a chain of modifiers left-to-right."""
    for mod in modifiers:
        value = apply_modifier(value, mod.name, mod.arg)
    return value
```

**Modifier implementations:**

| Modifier | Input Type | Output Type | Logic |
|----------|-----------|-------------|-------|
| `limit`  | list | list | `value[:int(arg)]`; cap arg at 100; if not list, return value unchanged |
| `join`   | list | str | `arg.join(str(item) for item in value)`; default arg=", " |
| `upper`  | str | str | `str(value).upper()` |
| `lower`  | str | str | `str(value).lower()` |
| `default`| any | any | if value is None or "" or [] -> return arg; else return value |
| `prefix` | any | str | if value is truthy -> f"{arg}{_format_value(value)}"; else "" |
| `suffix` | any | str | if value is truthy -> f"{_format_value(value)}{arg}"; else "" |
| `number` | int/float | str | `f"{value:,}"` for int; `f"{value:,.2f}"` for float; else str(value) |

**Important design note on `prefix`/`suffix`:** These call `_format_value()` internally because they produce the final display string. Other modifiers like `limit` preserve the native type.

#### 1d. Update `content_templates/renderer.py`

Refactor `SimpleTemplateRenderer` to use the AST internally:

```python
class SimpleTemplateRenderer:
    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict

    def render(self, template: str, context: Context) -> str:
        """Render template by parsing to AST and evaluating."""
        if not template:
            return ""
        nodes = parse(template)   # cached
        return self._render_nodes(nodes, context)

    def extract_fields(self, template: str) -> list[str]:
        """Return unique field names from template (includes condition fields)."""
        nodes = parse(template)
        seen: set[str] = set()
        result: list[str] = []
        self._collect_fields(nodes, seen, result)
        return result

    def _render_nodes(self, nodes, context) -> str:
        parts = []
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
        if node.field_name not in context:
            if self.strict:
                raise TemplateRenderError(f"Missing template field: {node.field_name}")
            return ""
        value = context[node.field_name]
        if node.modifiers:
            value = apply_modifier_chain(value, node.modifiers)
        return _format_value(value)

    def _evaluate_condition(self, cond: Condition, context: Context) -> bool:
        value = context.get(cond.field_name)
        if cond.operator == "truthy":
            return _is_truthy(value)
        # comparison operators...
        ...
```

**Truthiness rules for `{#if field}`:**
- `None` -> False
- `""` (empty string) -> False
- `0` (zero) -> False
- `0.0` -> False
- `[]` (empty list) -> False
- `False` -> False
- Everything else -> True

**Comparison rules for `{#if field > N}`:**
- Try to parse both sides as numbers. If both are numeric, compare numerically.
- If either side is non-numeric, compare as strings.
- If `value` is None, treat as less than any value (condition is False for `>`, `>=`).

**Critical:** `_format_value()` must remain unchanged. It's the existing function that converts values to display strings. The modifier chain runs BEFORE `_format_value()`.

**Critical:** `validate_template_body()` in renderer.py must also be updated to use the parser. It currently uses `_PLACEHOLDER_RE` and `_check_brace_balance()`. After this phase, it should parse via the AST and report errors from the parser.

#### 1e. Update `content_templates/validation.py`

Update `validate_template()` to use the parser for structural validation:
- Parse the template via `parse()` — structural errors (bad braces, nested ifs) are caught here
- Walk the AST to extract field names — check against `available_fields`
- Walk the AST to validate modifier type compatibility (e.g., `upper` after `limit` is invalid)

#### 1f. Update `content_templates/__init__.py`

Add new exports: `TemplateParseError`, `ModifierError`. Keep all existing exports.

#### 1g. Tests for Phase 1

Add to `tests/unit/test_content_templates.py`:

**Parser tests:**
- Simple `{field}` -> [PlaceholderNode]
- Text + placeholder -> [TextNode, PlaceholderNode, TextNode]
- `{field | limit:3}` -> PlaceholderNode with modifiers
- `{field | limit:3 | join:-}` -> chained modifiers
- `{#if field}text{/if}` -> IfBlockNode
- `{#if field > 5}text{/if}` -> condition with operator
- `{#if field}a{#else}b{/if}` -> if/else
- Nested `{#if}` -> TemplateParseError
- Unmatched `{/if}` -> TemplateParseError
- Unmatched `{#if}` -> TemplateParseError

**Modifier tests:**
- `limit` on list -> truncated list
- `limit` capped at 100
- `join` on list -> string
- `upper`/`lower` on string
- `default` on None -> default value
- `prefix`/`suffix` on truthy and falsy
- `number` on int, float
- Unknown modifier -> ModifierError
- Chain: `limit:3 | join:-` on list -> string

**Render integration tests:**
- Existing plain `{field}` templates produce identical output (regression)
- `{field | upper}` renders correctly
- `{#if field}text{/if}` with truthy/falsy context
- `{#if field > 5}text{/if}` with various values
- `{#if field}a{#else}b{/if}` both branches
- Nested placeholder inside conditional: `{#if count}{count}x{/if}`
- Modifier inside conditional: `{#if items}{items | limit:3}{/if}`

**Validation tests:**
- Valid templates pass (including new syntax)
- Unknown fields generate warnings (as before)
- Invalid modifier names raise error
- Nested `{#if}` raises error
- Unmatched blocks raise error

---

### Phase 2: Conditional Blocks (full feature)

**Goal:** `{#if}`, `{#else}`, `{/if}` with comparison operators fully working end-to-end.

**Note:** If Phase 1 is implemented correctly, Phase 2 is mostly already done — the parser and renderer already handle IfBlockNode. This phase is about:

1. Verifying all comparison operators work correctly with edge cases
2. Adding comprehensive tests for all operator types
3. Ensuring the Django API (preview endpoint) works with conditionals
4. Verifying compose.py still works (it calls renderer.render, which now handles conditionals)

**Edge case tests to add:**
- `{#if field = 0}` — should NOT match when field is 0 (string "0" vs int 0)
- `{#if field > 0}` — should work with float values (0.5 > 0 is true)
- `{#if field = }` — empty comparison value, should match when field is ""
- `{#if field != }` — should match when field is non-empty
- `{#if missing_field}` — field not in context, should be falsy
- `{#if missing_field > 5}` — field not in context, comparison is false

---

### Phase 3: Title Separator Assembly

**Goal:** After rendering a title template, clean up orphaned separators.

**File to create:**

#### 3a. `content_templates/postprocess.py` (NEW)

```python
def assemble_title_segments(rendered: str, separator: str = " | ") -> str:
    """Split rendered title by separator, remove empty segments, rejoin.

    Only used for title templates. Description templates skip this step.
    """
    segments = rendered.split(separator)
    cleaned = [seg.strip() for seg in segments if seg.strip()]
    return separator.join(cleaned)
```

#### 3b. Integration point

The `compose_with_templates()` function in `compose.py` needs to know whether a template is a title or description. Currently it doesn't — it just calls `renderer.render()`.

**Options (choose one):**

**Option A (recommended):** Add a `template_type` parameter to `compose_with_templates()`:

```python
def compose_with_templates(context, *, title_templates=None, description_templates=None):
    # titles are already known to be titles, descriptions known to be descriptions
    # Apply assemble_title_segments() to title results only
    if title_templates:
        for marketplace, body in title_templates.items():
            rendered = renderer.render(body, context)
            rendered = assemble_title_segments(rendered)  # <-- title only
            result.marketplace_titles[marketplace] = rendered
    ...
```

This is clean because the caller already passes `title_templates` and `description_templates` separately.

**Option B:** Make `SimpleTemplateRenderer.render()` accept a `template_type` parameter. This leaks presentation concerns into the renderer.

Go with Option A.

#### 3c. Tests

- `"A |  | B"` -> `"A | B"`
- `" | B"` -> `"B"`
- `"A | "` -> `"A"`
- `" |  | "` -> `""`
- `"A | B | C"` -> `"A | B | C"` (no change needed)
- `"A"` -> `"A"` (no separator)
- `""` -> `""` (empty)
- Custom separator: `"A -  - B"` with sep=`" - "` -> `"A - B"`

---

### Phase 4: Marketplace Length Validation

**Goal:** Hard-fail at compose time when rendered content exceeds marketplace limits.

**Where:** This validation goes in `compose.py` — after rendering and title assembly, before returning the result.

**Marketplace limits** (from legacy generators, store as constants):

```python
TITLE_MAX_LENGTHS = {
    "eldorado": 150,
    "g2g": 120,
    "gameboost": 140,
    "playerauctions": 140,
}
TITLE_DEFAULT_MAX_LENGTH = 150

DESCRIPTION_MAX_LENGTHS = {
    "eldorado": 1900,
    "g2g": 2000,
    "gameboost": 1900,
    "playerauctions": 2000,
}
DESCRIPTION_DEFAULT_MAX_LENGTH = 2000
```

**Behavior:**
- At compose time: if rendered title/description exceeds the marketplace limit, add a warning to the compose result. The composer (game-specific) decides whether to treat this as fatal.
- At preview time (API): always show the character count and warn if exceeded.
- Do NOT auto-truncate. Silent truncation produces broken titles.

**Implementation note:** This may require `compose_with_templates()` to return warnings alongside rendered content. The `TemplateComposeResult` dataclass could gain a `warnings: list[str]` field.

---

### Phase 5: UI Enhancements

**Goal:** Update the template editor frontend to support the new syntax.

This phase is the most flexible — it can be done incrementally. Key features:

#### 5a. Field palette updates

The field palette in `content_templates.html` currently shows fields with a "click to insert" button that copies `{field_name}`. Extend this:

- Add a "Modifiers" dropdown next to each field. When a modifier is selected, insert `{field_name | modifier}` or `{field_name | modifier:arg}` (prompt for arg).
- Show field type (list, string, number, boolean) so users know which modifiers apply.

#### 5b. Conditional block helper

Add a "Conditional" button in the toolbar that inserts a `{#if field}...{/if}` skeleton:

1. User clicks "Add Conditional"
2. Modal shows: field dropdown + operator dropdown + value input
3. On confirm, inserts `{#if field > value}|{/if}` with cursor positioned at `|`

#### 5c. Live preview with character count

The existing preview endpoint (`/api/content-templates/preview/`) already works. Enhance it to:

- Show character count per marketplace
- Show warning badges when limits are exceeded
- Show `{#if}` evaluation results (which blocks were included/excluded)

#### 5d. Syntax highlighting (optional, low priority)

In the template body textarea, highlight:
- `{field_name}` in blue
- `{#if ...}`, `{#else}`, `{/if}` in purple
- `| modifier:arg` in green
- Unknown fields in red

This can be done with a transparent overlay div or a CodeMirror instance.

---

## Key Files Reference

These are the files you'll need to read and understand before starting:

### Must-read before ANY phase:
- `libs/payload_pipeline/payload_pipeline/content_templates/renderer.py` — current renderer
- `libs/payload_pipeline/payload_pipeline/content_templates/validation.py` — current validation
- `libs/payload_pipeline/payload_pipeline/content_templates/compose.py` — how renderer is called
- `libs/payload_pipeline/payload_pipeline/content_templates/__init__.py` — public API
- `libs/payload_pipeline/tests/unit/test_content_templates.py` — existing tests

### Must-read for understanding context flow:
- `libs/payload_pipeline/payload_pipeline/core/contracts.py` — ListingDraft, MarketplaceListingOverride, etc.
- `libs/payload_pipeline/payload_pipeline/core/context_keys.py` — TITLE_TEMPLATES, DESCRIPTION_TEMPLATES
- `libs/payload_pipeline/payload_pipeline/content_templates/field_registry.py` — how field metadata works

### Must-read for understanding real usage:
- `libs/payload_pipeline/payload_pipeline/games/r6/account/content/composer.py` — how a game composer calls template rendering
- `libs/payload_pipeline/payload_pipeline/games/r6/account/content/title_generator.py` — the legacy code templates aim to replace
- `libs/payload_pipeline/payload_pipeline/games/r6/account/content/template_content.py` — how build_r6_context() produces the flat dict

### Must-read for frontend (Phase 5 only):
- `frontend/templates/posting/content_templates.html` — template editor UI
- `backend/apps/posting/api/content_templates.py` — Django API for templates

---

## Testing Strategy

### Run existing tests first

Before any code change, run:

```bash
cd libs/payload_pipeline
python -m pytest tests/unit/test_content_templates.py -v
```

All existing tests must pass throughout all phases.

### Test file location

Add all new tests to the existing file:

```
libs/payload_pipeline/tests/unit/test_content_templates.py
```

Group new tests in clearly named classes:

```python
class TestParser:
    ...

class TestModifiers:
    ...

class TestConditionalRendering:
    ...

class TestTitleSeparatorAssembly:
    ...
```

### Regression safety

After each phase, verify that the existing tests in `TestSimpleRenderer`, `TestValidation`, `TestComposition`, `TestRobloxIntegration` (or however they're currently organized) still pass with zero changes. If any existing test needs modification, that's a signal that backward compatibility is broken — investigate before proceeding.

---

## Critical Constraints

1. **No external dependencies.** The parser must be pure Python. No `pyparsing`, no `lark`, no `ply`. The payload_pipeline lib is dependency-light by design.

2. **Security first.** Every new input path (modifier args, condition values) must be validated. The flat-context + whitelist-regex security model must be preserved.

3. **`SimpleTemplateRenderer.render(template, context)` signature is sacred.** Do not change it. Internal implementation can change freely, but the public API must be backward compatible.

4. **`_format_value()` is the single source of truth for value-to-string conversion.** Modifiers that need string output should call it, but the final conversion after the modifier chain also calls it. Do not duplicate this logic.

5. **Templates are plain text, not HTML.** The renderer never produces HTML. `<br>` conversion is a separate builder-layer concern.

6. **Parser output should be cacheable.** Templates are stored in the DB and rendered many times with different contexts. Parsing the same template string twice should return cached results.
