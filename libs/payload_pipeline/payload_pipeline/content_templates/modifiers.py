"""Modifier registry and type-preserving execution.

Modifiers transform context values in a pipe chain before the final
string conversion.  Each modifier receives the native type from the
previous modifier; ``_format_value()`` is called only once at the end
of the chain (by the renderer).

Example chain::

    {items | limit:3 | join:-}
    list -> limit -> list -> join -> str -> (no final _format_value needed, already str)
"""

from __future__ import annotations

from typing import Any

from .ast_nodes import Modifier


class ModifierError(ValueError):
    """Raised when a modifier cannot be applied."""


def apply_modifier_chain(value: Any, modifiers: tuple[Modifier, ...]) -> Any:
    """Apply a chain of modifiers left-to-right, returning the transformed value."""
    for mod in modifiers:
        value = _apply_single(value, mod.name, mod.arg)
    return value


def _apply_single(value: Any, name: str, arg: str | None) -> Any:
    handler = _MODIFIER_REGISTRY.get(name)
    if handler is None:
        raise ModifierError(f"Unknown modifier: {name}")
    return handler(value, arg)


# ---------------------------------------------------------------------------
# Modifier implementations
# ---------------------------------------------------------------------------

def _mod_limit(value: Any, arg: str | None) -> Any:
    if not isinstance(value, list):
        return value
    n = int(arg) if arg else 10
    n = min(n, 100)  # cap at 100
    return value[:n]


_JOIN_ALIASES: dict[str, str] = {
    "pipe": " | ",
    "comma": ", ",
    "dash": " - ",
    "hash": " # ",
    "space": " ",
    "newline": "\n",
}


def _mod_join(value: Any, arg: str | None) -> str:
    if not isinstance(value, list):
        return str(value) if value is not None else ""
    separator = _JOIN_ALIASES.get(arg.strip(), arg) if arg is not None else ", "
    return separator.join(str(item) for item in value if item is not None)


def _mod_upper(value: Any, _arg: str | None) -> str:
    return str(value).upper() if value is not None else ""


def _mod_lower(value: Any, _arg: str | None) -> str:
    return str(value).lower() if value is not None else ""


def _mod_default(value: Any, arg: str | None) -> Any:
    if value is None or value == "" or value == []:
        return arg if arg is not None else ""
    return value


def _mod_prefix(value: Any, arg: str | None) -> str:
    if not _is_truthy(value):
        return ""
    from .renderer import _format_value
    return f"{arg or ''}{_format_value(value)}"


def _mod_suffix(value: Any, arg: str | None) -> str:
    if not _is_truthy(value):
        return ""
    from .renderer import _format_value
    return f"{_format_value(value)}{arg or ''}"


def _mod_number(value: Any, _arg: str | None) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value) if value is not None else ""


def _is_truthy(value: Any) -> bool:
    """Check if a value is truthy by template engine rules."""
    if value is None:
        return False
    if value == "":
        return False
    if value == 0 or value == 0.0:
        return False
    if value is False:
        return False
    if isinstance(value, list) and len(value) == 0:
        return False
    return True


_MODIFIER_REGISTRY: dict[str, Any] = {
    "limit": _mod_limit,
    "join": _mod_join,
    "upper": _mod_upper,
    "lower": _mod_lower,
    "default": _mod_default,
    "prefix": _mod_prefix,
    "suffix": _mod_suffix,
    "number": _mod_number,
}
