# RFC: Advanced Content Template Engine (v2 — revised after review)

## Status: Approved Design — Ready for Implementation

## Changelog

- **v1**: Initial draft with modifiers, conditionals, smart separator cleanup.
- **v2**: Incorporated external review feedback. Key changes:
  - Separator cleanup scoped to title-only with explicit separator (no auto-detect).
  - `{#else}` included from day one in parser design.
  - Nesting prohibited; RFC description example corrected (was violating its own rule).
  - Modifier chain is type-preserving (string conversion only at final step).
  - Marketplace length hard-validated at posting time, not just preview warning.
  - Internal architecture: small AST parser instead of regex-on-regex patching.

---

## 1. Problem Statement

We have a content template builder system for an e-commerce platform that generates listing titles and descriptions across multiple marketplaces (Eldorado, G2G, GameBoost, PlayerAuctions). The current template engine supports only simple `{field_name}` placeholder substitution:

```
R6 Account | Lv {level} | {current_rank} | {black_ice_count} BI
```

This works for basic cases, but **cannot express the conditional logic** that our legacy Python generators handle daily. The result: users must either accept rigid templates or we fall back to hardcoded generators that require developer intervention for every change.

### Real Example of the Gap

**What the user wants to write:**

> "If the account has Black Ice skins, show the count and the first 3 skin names. If it doesn't, skip that section entirely — including the separator before it."

**What they can write today:**

```
R6 Account | Lv {level} | {current_rank} | {black_ice_count}xBlack Ice
```

**Problem:** When `black_ice_count` is 0, this renders as:

```
R6 Account | Lv 120 | Diamond | 0xBlack Ice     <-- ugly, misleading
```

**What the legacy Python generator does (title_generator.py:59-60):**

```python
if account.black_ice_count > 0:
    parts.append(f"{account.black_ice_count}xBlack Ice")
# Otherwise: nothing added, no separator, clean output
```

This pattern repeats **50+ times** across 10 game title/description generators.

---

## 2. Production Patterns Analysis

We audited all legacy generators across 10 games (R6, Valorant, Fortnite, LoL, CoC, Genshin, Clash Royale, Brawl Stars, Roblox, CS2/GTA/Steam/Ubisoft). Five recurring patterns emerged:

### Pattern A: Conditional Section (50+ occurrences)

Show a segment only when a field has a meaningful value.

```python
# R6 title_generator.py:59
if account.black_ice_count > 0:
    parts.append(f"{account.black_ice_count}xBlack Ice")

# Fortnite title_generator.py:56-57
if account.platform == "EpicPC" and account.v_bucks >= 500:
    parts.append(f"{account.v_bucks} V-Bucks")

# LoL title_generator.py:49-50
if account.kind != "dropshipping":
    parts.append("Instant Delivery")
```

### Pattern B: List Truncation (15+ occurrences)

Take the first N items from a list field.

```python
# R6 title_generator.py:112
specials[:2]      # universals -> max 2
specials[:3]      # seasonals -> max 3

# R6 description_generator.py:81-87
items[:15]        # operator preview -> max 15

# Valorant description_generator.py:106-107
items[:25]        # skin items per category -> max 25
```

### Pattern C: Threshold Comparison (10+ occurrences)

Show field only above a specific numeric threshold.

```python
# LoL title_generator.py:33-35
if account.blue_essence > 5000:    parts.append(f"{account.blue_essence} BE")
if account.orange_essence > 3000:  parts.append(f"{account.orange_essence} OE")
if account.riot_points > 500:      parts.append(f"{account.riot_points} RP")
```

### Pattern D: Value Transform (8+ occurrences)

Format a field value differently than its raw form.

```python
# Brawl Stars: uppercase names
# CoC: comma-separated numbers (45,000)
# Genshin: region code mapping (North America -> NA)
```

### Pattern E: Separator-Aware Assembly (all games)

Join parts with ` | ` but skip empty parts and clean up orphaned separators.

```python
# Every game's _assemble():
sep = " | "
for part in parts:
    if current_length + len(part) > max_length:
        break
    final.append(part)
return sep.join(final)
```

---

## 3. Proposed Solution: AST Parser + Modifiers + Conditional Blocks

Extend the current `{field_name}` syntax with two new capabilities while preserving full backward compatibility. Internal architecture uses a small AST instead of regex patching.

### 3.1 Pipe Modifiers — `{field | modifier:arg}`

Extend placeholders with chainable, **type-preserving** modifiers using pipe syntax:

```
{black_ice_items | limit:3}              --> "R4-C, MP5, 416-C"
{black_ice_items | limit:3 | join: / }   --> "R4-C / MP5 / 416-C"
{current_rank | upper}                   --> "DIAMOND"
{blue_essence | suffix: BE}              --> "5000 BE"  (empty if field is empty)
{price | number}                         --> "45,000"
{tracker_url | default:N/A}              --> "N/A" when field is empty
```

**Modifier catalog:**

| Modifier   | Argument | Input Type | Output Type | Example In         | Example Out     | Use Case                    |
|------------|----------|------------|-------------|--------------------|-----------------|-----------------------------|
| `limit`    | N        | list       | list        | `["A","B","C","D"]`| `["A","B","C"]` | List truncation             |
| `join`     | separator| list       | str         | `["A","B"]`        | `"A-B"`         | Custom list separator       |
| `upper`    | --       | str        | str         | `"diamond"`        | `"DIAMOND"`     | Case transform              |
| `lower`    | --       | str        | str         | `"Diamond"`        | `"diamond"`     | Case transform              |
| `default`  | value    | any        | any         | `None`             | `"N/A"`         | Fallback for empty fields   |
| `prefix`   | text     | any        | str         | `5000`             | `"BE: 5000"`    | Conditional prefix (skips if empty) |
| `suffix`   | text     | any        | str         | `5000`             | `"5000 BE"`     | Conditional suffix (skips if empty) |
| `number`   | --       | int/float  | str         | `45000`            | `"45,000"`      | Thousands separator         |

**Type-preserving chaining:** Each modifier receives the native type from the previous modifier. `_format_value()` (the final string conversion) is called only once, at the end of the chain, after all modifiers have run. This means:

- `{items | limit:3}` -- limit receives list, returns list, final format joins with ", "
- `{items | limit:3 | join:-}` -- limit receives list, returns list; join receives list, returns str
- `{items | limit:3 | upper}` -- INVALID: upper expects str but receives list (validation error)

The modifier pipeline: `context_value -> mod1 -> mod2 -> ... -> _format_value() -> string`

### 3.2 Conditional Blocks — `{#if field}...{#else}...{/if}`

Wrap template sections in conditional blocks that are included or excluded based on field values:

```
{#if black_ice_count}{black_ice_count}xBLACK ICES | {/if}{level} LEVEL
```

**When `black_ice_count = 12`:**
```
12xBLACK ICES | 120 LEVEL
```

**When `black_ice_count = 0`:**
```
120 LEVEL
```

**With `{#else}` (included from day one):**
```
{#if current_rank}{current_rank}{#else}Unranked{/if}
```

**Supported operators:**

| Syntax                        | Meaning                     | Example                              |
|-------------------------------|-----------------------------|--------------------------------------|
| `{#if field}`                 | Field is truthy (>0, non-empty, not None) | `{#if black_ice_count}`   |
| `{#if field > N}`             | Greater than                | `{#if blue_essence > 5000}`          |
| `{#if field >= N}`            | Greater than or equal       | `{#if level >= 100}`                 |
| `{#if field = value}`         | Equals (string or number)   | `{#if platform = PC}`               |
| `{#if field != value}`        | Not equals                  | `{#if kind != dropshipping}`         |
| `{#else}`                     | Else branch                 | `{#if rank}{rank}{#else}Unranked{/if}` |
| `{/if}`                       | End of conditional block    |                                      |

**Design constraints:**
- **No nesting.** `{#if}` blocks cannot contain other `{#if}` blocks. This keeps the parser simple and templates readable. Complex conditional logic belongs in the context builder as pre-computed display fields (e.g., `rank_label`, `champion_tier_label`).
- **`{#else}` is supported.** This avoids forcing users to write two inverse conditions. The parser always supports `{#if}...{#else}...{/if}` as a single block.
- **Placeholders inside conditionals** work normally: `{#if count}{count}x Items{/if}` renders the inner `{count}` placeholder.
- **Modifiers inside conditionals** work: `{#if items}{items | limit:3}{/if}`

### 3.3 Title Separator Assembly (Title Templates Only)

Title templates declare an explicit separator. After conditional evaluation, the engine:
1. Splits the rendered string by the separator
2. Trims each segment and removes empty segments
3. Rejoins with the separator

This runs **only for title templates** (declared by `template_type="title"` in the DB model). Description templates receive no separator processing — their content is rendered as-is.

**Why not auto-detect?** Descriptions may contain `|` in URLs, table-like text, or natural prose. Auto-detecting separators there would corrupt content.

**Separator value:** Defaults to `" | "`. Can be overridden per-template if needed in the future (stored as template metadata), but for now the default covers all current games.

**Example:**

```
Template:  {#if glacier_count}{glacier_count}xGlacier{/if} | {#if black_ice_count}{black_ice_count}xBI{/if} | Full Access
Context:   glacier_count=0, black_ice_count=0

After conditionals:  " |  | Full Access"
After separator assembly:  "Full Access"

Context:   glacier_count=2, black_ice_count=0

After conditionals:  "2xGlacier |  | Full Access"
After separator assembly:  "2xGlacier | Full Access"
```

---

## 4. Full Real-World Examples

### R6 Title Template (replaces 134 lines of Python)

```
[PC] | {#if level}Level {level}{/if} | {#if current_rank}{current_rank}{/if} | {#if peak_rank}{peak_rank}{/if} | {#if skin_count}{skin_count} Skins{/if} | {#if operator_count}{operator_count} Operators{/if} | {#if glacier_count}{glacier_count}xGlacier{/if} | {#if black_ice_count}{black_ice_count}xBlack Ice{/if} | {#if black_ice_items}({black_ice_items | limit:3 | join:-}){/if} | Full Access | {#if kind != dropshipping}Instant Delivery{/if}
```

Note: separators are between segments. Empty segments (from false conditionals) are removed by title separator assembly, so no orphaned `|` appear.

**Context A** (rich account):
```
level=120, current_rank=Diamond, skin_count=450, black_ice_count=12,
black_ice_items=["R4-C","MP5","416-C","P90"], glacier_count=2, kind=stock
```
**Output A:**
```
[PC] | Level 120 | Diamond | 450 Skins | 12xBlack Ice | (R4-C-MP5-416-C) | 2xGlacier | Full Access | Instant Delivery
```

**Context B** (basic account):
```
level=45, current_rank=Gold, skin_count=0, black_ice_count=0,
glacier_count=0, kind=dropshipping
```
**Output B:**
```
[PC] | Level 45 | Gold | Full Access
```

### R6 Description Template (excerpt)

```
Level: {level}
Rank: {#if current_rank}{current_rank}{#else}Ranked Ready{/if}

{#if black_ice_count}Black Ice Skins ({black_ice_count}):
{black_ice_items | limit:15 | join:, }
{/if}
{#if glacier_count}Glacier Skins ({glacier_count}):
{glacier_items | limit:10 | join:, }
{/if}
{#if album_url}Screenshots: {album_url}{/if}

{#if kind != dropshipping}Instant Delivery{/if}
```

Note: No nesting. The old v1 example `{#if current_rank = }{#if ranked_ready}...` was nested and violated the no-nesting rule. Fixed using `{#else}` instead.

---

## 5. Security Model

### Current protections (preserved)

- **Regex-based placeholder extraction** -- no `str.format_map()`, no attribute traversal (`{field.__class__}` impossible)
- **Whitelist pattern** -- only `[a-zA-Z_][a-zA-Z0-9_]*` allowed as field names
- **Flat context dict** -- no object access, no method calls
- **Credentials excluded** -- context builders always skip `credentials` field

### New attack surfaces to guard against

| Risk | Mitigation |
|------|-----------|
| ReDoS via crafted modifier args | Modifier args validated: alphanumeric + limited punctuation only |
| Infinite loops via nested `{#if}` | Nesting prohibited at parse time; max block count enforced (default: 50) |
| Resource exhaustion via huge `limit` | `limit` capped at 100 items |
| Modifier injection via field values | Modifiers are parsed from template only, never from context values |
| Type confusion in modifier chain | Modifier type compatibility validated at template save time |

### What we intentionally do NOT support

- **No loops / iteration** (`{#for item in list}`) -- use `{list_field | limit:N}` instead
- **No arithmetic** (`{price * 1.1}`) -- compute in context builder
- **No nested field access** (`{inventory.glaciers.count}`) -- flatten in context builder
- **No raw HTML output** -- all values are plain text
- **No external includes** -- templates are self-contained
- **No nested conditionals** -- use `{#else}` or computed display fields

---

## 6. Architecture

### Processing pipeline

```
Template Body (string from DB)
        |
        v
[1] Parse -> AST                     TextNode, PlaceholderNode, IfBlockNode
        |
        v
[2] Evaluate AST                     Walk tree, evaluate conditions,
        |                             resolve placeholders with modifier chains
        v
[3] Collect rendered segments         Each node produces a string fragment
        |
        v
[4] Title separator assembly          (title only) split by separator,
        |                             remove empty segments, rejoin
        v
Rendered string
```

### AST Node Types

```python
@dataclass
class TextNode:
    """Literal text that passes through unchanged."""
    text: str

@dataclass
class PlaceholderNode:
    """A {field_name} or {field | mod:arg | mod} reference."""
    field_name: str
    modifiers: list[Modifier]   # parsed modifier chain

@dataclass
class Modifier:
    """A single modifier in a pipe chain."""
    name: str                   # "limit", "join", "upper", etc.
    arg: str | None             # "3", "-", "N/A", etc.

@dataclass
class IfBlockNode:
    """A {#if condition}...{#else}...{/if} block."""
    condition: Condition
    if_body: list[Node]         # nodes when condition is true
    else_body: list[Node]       # nodes when condition is false (may be empty)

@dataclass
class Condition:
    """Parsed condition from {#if field > value}."""
    field_name: str
    operator: str               # "truthy", ">", ">=", "=", "!="
    value: str | None           # comparison target (None for truthy check)
```

### Why AST instead of regex patching

The current renderer uses a single regex (`_PLACEHOLDER_RE`) for `{field}` substitution. Adding `{#if}`, `{#else}`, `{/if}`, and `{field | mod}` via additional regexes would require:

- One regex for conditionals, another for placeholders-with-modifiers, plus the existing one
- Separate regex passes for validation, field extraction, and unknown-field warnings
- Coordination between passes (conditionals must be evaluated before placeholders inside them)

This compounds quickly and produces brittle, hard-to-debug code. A small parser that produces an AST solves all concerns in one pass:

- **render()** walks the AST and produces the output string
- **extract_fields()** walks the AST and collects field names from PlaceholderNode + IfBlockNode
- **validate()** walks the AST and checks modifier type compatibility + field existence
- Error messages include position information from the parse step

The parser itself is ~100-150 lines (character-by-character scanner, no external dependencies). The AST nodes are simple frozen dataclasses.

### Module structure

```
content_templates/
    __init__.py               # Public API (unchanged exports + new ones)
    renderer.py               # SimpleTemplateRenderer (updated to use AST internally)
    parser.py                 # NEW: Tokenizer + AST builder
    ast_nodes.py              # NEW: TextNode, PlaceholderNode, IfBlockNode, Condition, Modifier
    modifiers.py              # NEW: Modifier registry, type-preserving execution
    validation.py             # Extended: AST-based validation
    compose.py                # Unchanged (calls renderer.render as before)
    field_registry.py         # Unchanged
```

### Backward compatibility

- All existing `{field_name}` templates render identically -- zero changes needed
- `SimpleTemplateRenderer.render(template, context)` signature unchanged
- `validate_template_body()` extended but all existing valid templates pass without warnings
- New features are opt-in: templates without `{#if}` or `|` parse into a flat list of TextNode + PlaceholderNode (no IfBlockNode), and render via the same code path

---

## 7. Scope Boundary: Template vs Context Builder

The template engine handles **presentation logic**. Business logic stays in context builders.

| Template engine (presentation)          | Context builder (business logic)        |
|-----------------------------------------|-----------------------------------------|
| `{#if count > 0}show count{/if}`       | Sorting valuable skins to top           |
| `{items \| limit:3}`                    | Cross-category deduplication            |
| `{field \| upper}`                      | Dynamic budget-based item fitting       |
| `{field \| prefix:BE: }`               | `if count >= 160: "All Champs"`         |
| `{#if rank}{rank}{#else}Unranked{/if}` | Priority ordering, blacklist filtering  |
| Title separator assembly                | Pre-computing derived fields            |

**Guideline:** If the logic requires comparing two fields against each other, iterating with state, or applying business rules, it should produce a pre-computed display field in the context dict (e.g., `top_3_black_ices`, `champion_label`, `rank_display`). The template then simply references that field.

---

## 8. Marketplace Length Handling

### Preview (UI)

Show a live character count with marketplace-specific limits:

```
Title: "R6 Account | Lv 120 | Diamond | ..."
Characters: 142 / 150 (eldorado)    [OK]
Characters: 142 / 120 (g2g)         [WARNING: exceeds limit]
```

### Production (posting time)

At compose time, if the rendered title exceeds the marketplace character limit, the result is a **hard failure**:

```python
PrepareResult(success=False, error_stage="compose",
    error="Title exceeds g2g limit: 142 > 120 characters")
```

This is fail-fast behavior. The user must either shorten the template or use a separate, shorter template for that marketplace. No silent truncation.

### Per-marketplace limits (from legacy generators)

| Marketplace     | Title Max | Description Max |
|-----------------|-----------|-----------------|
| eldorado        | 150       | 1900            |
| g2g             | 120       | 2000            |
| gameboost       | 140       | 1900            |
| playerauctions  | 140       | 2000            |

---

## 9. Decisions (formerly Open Questions)

1. **`{#else}` support:** YES -- included from day one. Parser design accommodates it; implementation is Phase 2 alongside `{#if}`.

2. **Max template length after render:** Hard validation at posting time (fail-fast). Preview shows character count with warnings. No auto-truncation.

3. **Separator handling:** Title templates use explicit separator (default `" | "`). Separator assembly is title-only. Descriptions receive no separator processing.

4. **Description newlines:** `\n` to `<br>` conversion stays in the builder layer (marketplace-specific post-processing). Template engine outputs plain text only.

5. **Nesting:** Prohibited. The parser rejects `{#if}` inside another `{#if}` block at parse time. Use `{#else}` for simple alternation; use computed display fields for complex cases.
