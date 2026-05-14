"""Template parser — converts a template string into an AST.

Produces a tuple of :class:`Node` objects that the renderer walks to
produce output.  The parser is a simple character-by-character scanner
with no external dependencies.

Parsing rules:
- Outside ``{...}``: accumulate text into :class:`TextNode`.
- ``{#if ...}``: parse condition, scan body until ``{#else}`` or ``{/if}``.
- ``{#else}``: switch to else_body inside an ``{#if}`` block.
- ``{/if}``: close the current :class:`IfBlockNode`.
- ``{field}`` or ``{field | mod:arg}``: produce :class:`PlaceholderNode`.
- Nested ``{#if}`` inside another ``{#if}``: raise immediately.

Results are cached via :func:`functools.lru_cache` since templates are
rendered many times with different contexts.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .ast_nodes import (
    Condition,
    IfBlockNode,
    Modifier,
    Node,
    PlaceholderNode,
    TextNode,
)

# Validation patterns
_FIELD_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*$")
_MODIFIER_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*$")
_MODIFIER_ARG_RE = re.compile(r"[a-zA-Z0-9_ /,.:;!?\-]*$")

# Comparison operators (ordered longest-first for greedy matching)
_COMPARISON_OPS = (">=", "<=", "!=", ">", "<", "=")

_MAX_IF_BLOCKS = 50


class TemplateParseError(ValueError):
    """Raised when a template cannot be parsed."""

    def __init__(self, message: str, position: int | None = None) -> None:
        self.position = position
        if position is not None:
            message = f"{message} (position {position})"
        super().__init__(message)


@lru_cache(maxsize=256)
def parse(template: str) -> tuple[Node, ...]:
    """Parse a template string into an AST node tuple."""
    parser = _Parser(template)
    return parser.parse()


class _Parser:
    """Character-by-character template scanner."""

    def __init__(self, template: str) -> None:
        self._src = template
        self._pos = 0
        self._if_block_count = 0

    def parse(self) -> tuple[Node, ...]:
        nodes = self._parse_nodes(top_level=True)
        return tuple(nodes)

    def _parse_nodes(
        self,
        *,
        top_level: bool = False,
        inside_if: bool = False,
    ) -> list[Node]:
        """Parse nodes until end-of-input or a control tag (``{#else}``, ``{/if}``)."""
        nodes: list[Node] = []
        text_start = self._pos

        while self._pos < len(self._src):
            ch = self._src[self._pos]

            if ch == "{":
                # Flush accumulated text
                if self._pos > text_start:
                    nodes.append(TextNode(self._src[text_start : self._pos]))

                tag_start = self._pos
                tag_content = self._read_brace_content()

                if tag_content.startswith("#if ") or tag_content == "#if":
                    node = self._parse_if_block(tag_content, tag_start, inside_if)
                    nodes.append(node)
                elif tag_content == "#else":
                    if not inside_if:
                        raise TemplateParseError(
                            "Unexpected {#else} outside of {#if} block",
                            tag_start,
                        )
                    # Signal to caller that we hit {#else}
                    self._hit_else = True
                    return nodes
                elif tag_content == "/if":
                    if not inside_if:
                        raise TemplateParseError(
                            "Unexpected {/if} without matching {#if}",
                            tag_start,
                        )
                    self._hit_endif = True
                    return nodes
                else:
                    # Regular placeholder (possibly with modifiers)
                    nodes.append(self._parse_placeholder(tag_content, tag_start))

                text_start = self._pos
            else:
                self._pos += 1

        # Flush remaining text
        if self._pos > text_start:
            nodes.append(TextNode(self._src[text_start : self._pos]))

        if inside_if and not getattr(self, "_hit_endif", False):
            raise TemplateParseError("Unclosed {#if} block")

        return nodes

    def _read_brace_content(self) -> str:
        """Read content between ``{`` and ``}``, advancing past the closing brace."""
        assert self._src[self._pos] == "{"
        start = self._pos
        self._pos += 1  # skip {

        depth = 1
        while self._pos < len(self._src):
            ch = self._src[self._pos]
            if ch == "{":
                raise TemplateParseError("Nested braces are not supported", self._pos)
            if ch == "}":
                content = self._src[start + 1 : self._pos]
                self._pos += 1  # skip }
                return content
            self._pos += 1

        raise TemplateParseError("Unclosed brace in template", start)

    def _parse_if_block(
        self, tag_content: str, tag_start: int, already_inside_if: bool
    ) -> IfBlockNode:
        """Parse a complete ``{#if ...}...{#else}...{/if}`` block."""
        if already_inside_if:
            raise TemplateParseError(
                "Nested {#if} blocks are not supported", tag_start
            )

        self._if_block_count += 1
        if self._if_block_count > _MAX_IF_BLOCKS:
            raise TemplateParseError(
                f"Too many {{#if}} blocks (max {_MAX_IF_BLOCKS})", tag_start
            )

        condition = self._parse_condition(tag_content[3:].strip(), tag_start)

        # Parse if-body
        self._hit_else = False
        self._hit_endif = False
        if_body = self._parse_nodes(inside_if=True)

        else_body: list[Node] = []
        if self._hit_else:
            # Parse else-body
            self._hit_else = False
            self._hit_endif = False
            else_body = self._parse_nodes(inside_if=True)
            if not self._hit_endif:
                raise TemplateParseError("Unclosed {#if} block (missing {/if} after {#else})")

        return IfBlockNode(
            condition=condition,
            if_body=tuple(if_body),
            else_body=tuple(else_body),
        )

    def _parse_condition(self, raw: str, pos: int) -> Condition:
        """Parse condition expression like ``field``, ``field > 5000``."""
        if not raw:
            raise TemplateParseError("Empty {#if} condition", pos)

        for op in _COMPARISON_OPS:
            idx = raw.find(f" {op} ")
            if idx != -1:
                field_name = raw[:idx].strip()
                value = raw[idx + len(op) + 2 :].strip()
                self._validate_field_name(field_name, pos)
                return Condition(field_name=field_name, operator=op, value=value)
            # Also check if operator is at end (e.g., "field > " with trailing space or "field >value")
            if f" {op}" in raw and raw.endswith(op):
                # "field >"  — no value
                field_name = raw[: raw.rfind(f" {op}")].strip()
                self._validate_field_name(field_name, pos)
                return Condition(field_name=field_name, operator=op, value="")

        # No operator found — truthy check
        field_name = raw.strip()
        self._validate_field_name(field_name, pos)
        return Condition(field_name=field_name, operator="truthy", value=None)

    def _parse_placeholder(self, content: str, pos: int) -> PlaceholderNode:
        """Parse ``field`` or ``field | mod:arg | mod2`` into a PlaceholderNode."""
        # Split by " | " for modifiers
        parts = content.split(" | ")
        field_part = parts[0]
        field_name = field_part.strip()

        # If there are no modifiers, the field name must match the entire content
        # (no stray whitespace). This catches "{ space }" as invalid.
        if len(parts) == 1 and field_name != content.strip():
            # content has spaces that aren't part of modifier syntax
            pass  # _validate_field_name will catch truly invalid names

        # If the raw field part has leading/trailing spaces and no modifiers,
        # the original brace content is suspicious (e.g., "{ space }").
        if field_part != field_part.strip() and " | " not in content:
            raise TemplateParseError(
                f"Invalid placeholder syntax: {{{content}}} — "
                "use {{field_name}} with letters, digits, and underscores only",
                pos,
            )

        self._validate_field_name(field_name, pos)

        modifiers: list[Modifier] = []
        for i, part in enumerate(parts[1:], 1):
            stripped = part.strip()
            if not stripped:
                raise TemplateParseError(f"Empty modifier in pipe chain", pos)
            modifiers.append(self._parse_modifier(part, pos))

        return PlaceholderNode(
            field_name=field_name,
            modifiers=tuple(modifiers),
        )

    def _parse_modifier(self, raw: str, pos: int) -> Modifier:
        """Parse a single modifier like ``limit:3`` or ``upper``."""
        colon_idx = raw.find(":")
        if colon_idx == -1:
            name = raw.strip()
            self._validate_modifier_name(name, pos)
            return Modifier(name=name)

        name = raw[:colon_idx].strip()
        arg = raw[colon_idx + 1:]  # preserve leading space in arg (e.g., "join: / ")
        self._validate_modifier_name(name, pos)
        self._validate_modifier_arg(arg, pos)
        return Modifier(name=name, arg=arg)

    def _validate_field_name(self, name: str, pos: int) -> None:
        if not name or not _FIELD_NAME_RE.match(name):
            raise TemplateParseError(
                f"Invalid placeholder syntax: {{{name}}} — "
                "use {{field_name}} with letters, digits, and underscores only",
                pos,
            )

    def _validate_modifier_name(self, name: str, pos: int) -> None:
        if not name or not _MODIFIER_NAME_RE.match(name):
            raise TemplateParseError(
                f"Invalid modifier name: {name!r}", pos
            )

    def _validate_modifier_arg(self, arg: str, pos: int) -> None:
        if not _MODIFIER_ARG_RE.match(arg):
            raise TemplateParseError(
                f"Invalid modifier argument: {arg!r}", pos
            )
