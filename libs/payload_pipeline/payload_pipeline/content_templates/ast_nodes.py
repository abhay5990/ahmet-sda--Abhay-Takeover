"""AST node types for the template engine.

The parser produces a tree of these nodes from a template string.
The renderer walks the tree to produce output.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Modifier:
    """A single modifier in a pipe chain, e.g. ``limit:3`` or ``upper``."""

    name: str
    arg: str | None = None


@dataclass(frozen=True, slots=True)
class TextNode:
    """Literal text that passes through unchanged."""

    text: str


@dataclass(frozen=True, slots=True)
class PlaceholderNode:
    """A ``{field_name}`` or ``{field | mod:arg | mod}`` reference."""

    field_name: str
    modifiers: tuple[Modifier, ...] = ()


@dataclass(frozen=True, slots=True)
class Condition:
    """Parsed condition from ``{#if field > value}``."""

    field_name: str
    operator: str  # "truthy", ">", ">=", "<", "<=", "=", "!="
    value: str | None = None  # None for truthy check


@dataclass(frozen=True, slots=True)
class IfBlockNode:
    """A ``{#if condition}...{#else}...{/if}`` block."""

    condition: Condition
    if_body: tuple[Node, ...]
    else_body: tuple[Node, ...] = ()


# Union type for all AST nodes.
Node = TextNode | PlaceholderNode | IfBlockNode
