"""Per-game manual entry field specifications.

Each game registers a list of ``ManualFieldSpec`` that describes
the UI fields shown when a user creates a manual stock entry.
The Django layer reads these specs via the ``ManualFieldRegistry``
and renders them dynamically — no hardcoded ``if game == ...`` blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


FieldType = Literal["text", "number", "select", "multiselect", "boolean", "textarea"]


@dataclass(frozen=True, slots=True)
class FieldOption:
    """Single option for select / multiselect fields."""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ManualFieldSpec:
    """Declarative specification for one manual entry form field.

    Attributes:
        key: Canonical field identifier (e.g. ``region``, ``current_rank``).
        label: Human-readable label shown in the UI.
        field_type: Widget type — ``text``, ``number``, ``select``,
            ``multiselect``, or ``boolean``.
        required: Whether the field must be filled before submission.
        options: Available choices for ``select`` / ``multiselect`` types.
        default: Default value (must match ``field_type``).
        help_text: Optional hint shown below the field.
        group: Optional group label for UI sectioning
            (e.g. ``"Account Data"``, ``"Marketplace Attributes"``).
    """

    key: str
    label: str
    field_type: FieldType = "text"
    required: bool = False
    options: tuple[FieldOption, ...] = ()
    default: Any = None
    help_text: str = ""
    group: str = ""
    min_value: float | None = None


class ManualFieldRegistry:
    """Central registry of per-game manual field specs.

    Games register their specs at import time.  The Django API
    queries this registry to serve field definitions to the frontend.
    """

    def __init__(self) -> None:
        self._specs: dict[str, tuple[ManualFieldSpec, ...]] = {}

    def register(self, game: str, specs: list[ManualFieldSpec]) -> None:
        """Register field specs for a game (overwrites previous)."""
        self._specs[game.lower()] = tuple(specs)

    def get_specs(self, game: str) -> tuple[ManualFieldSpec, ...]:
        """Return field specs for a game, or empty tuple if not registered."""
        return self._specs.get(game.lower(), ())

    def has_specs(self, game: str) -> bool:
        return game.lower() in self._specs

    def list_games(self) -> list[str]:
        return sorted(self._specs.keys())

    def serialize(self, game: str) -> list[dict[str, Any]]:
        """Serialize specs to JSON-friendly dicts for the API response."""
        result = []
        for spec in self.get_specs(game):
            entry: dict[str, Any] = {
                "key": spec.key,
                "label": spec.label,
                "type": spec.field_type,
                "required": spec.required,
            }
            if spec.options:
                entry["options"] = [
                    {"value": o.value, "label": o.label} for o in spec.options
                ]
            if spec.default is not None:
                entry["default"] = spec.default
            if spec.help_text:
                entry["help_text"] = spec.help_text
            if spec.group:
                entry["group"] = spec.group
            if spec.min_value is not None:
                entry["min_value"] = spec.min_value
            result.append(entry)
        return result

    def validate_values(
        self,
        game: str,
        values: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Validate and normalize submitted manual field values for a game."""

        specs = self.get_specs(game)
        if not specs:
            if values:
                return {}, [f"No manual field specs registered for game '{game}'."]
            return {}, []

        if values is None:
            values = {}
        if not isinstance(values, dict):
            return {}, ["manual_fields must be an object."]

        specs_by_key = {spec.key: spec for spec in specs}
        errors: list[str] = []
        normalized: dict[str, Any] = {}

        for key in values:
            if key not in specs_by_key:
                errors.append(f"{key}: unknown field.")

        for spec in specs:
            raw = values.get(spec.key, spec.default)
            value, field_errors = _normalize_field_value(spec, raw)
            errors.extend(f"{spec.key}: {error}" for error in field_errors)
            if not field_errors and _should_store_value(spec, value, raw):
                normalized[spec.key] = value

        return normalized, errors


# Global singleton — games register against this instance.
manual_field_registry = ManualFieldRegistry()


def _normalize_field_value(
    spec: ManualFieldSpec,
    value: Any,
) -> tuple[Any, list[str]]:
    errors: list[str] = []

    if spec.field_type in ("text", "textarea", "select"):
        normalized = "" if value is None else str(value).strip()
        if spec.required and not normalized:
            errors.append("is required.")
            return normalized, errors
        if spec.field_type == "select" and normalized:
            allowed = {option.value for option in spec.options}
            if allowed and normalized not in allowed:
                errors.append(f"must be one of: {', '.join(sorted(allowed))}.")
        return normalized, errors

    if spec.field_type == "number":
        if value in (None, ""):
            if spec.required:
                errors.append("is required.")
            return None, errors
        if isinstance(value, bool):
            errors.append("must be a number.")
            return value, errors
        try:
            number = float(value)
        except (TypeError, ValueError):
            errors.append("must be a number.")
            return value, errors
        floor = spec.min_value if spec.min_value is not None else 0
        if number < floor:
            if floor == 0:
                errors.append("must be zero or greater.")
            else:
                errors.append(f"must be {floor:g} or greater.")
        normalized = int(number) if number.is_integer() else number
        return normalized, errors

    if spec.field_type == "boolean":
        if isinstance(value, bool):
            return value, errors
        if value in (None, ""):
            return False, errors
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True, errors
            if lowered in {"false", "0", "no", "off"}:
                return False, errors
        errors.append("must be a boolean.")
        return value, errors

    if spec.field_type == "multiselect":
        if value in (None, ""):
            normalized_list: list[str] = []
        elif isinstance(value, list):
            normalized_list = [str(item).strip() for item in value if str(item).strip()]
        else:
            errors.append("must be a list.")
            return value, errors
        if spec.required and not normalized_list:
            errors.append("is required.")
        allowed = {option.value for option in spec.options}
        invalid = [item for item in normalized_list if allowed and item not in allowed]
        if invalid:
            errors.append(f"contains invalid values: {', '.join(sorted(invalid))}.")
        return normalized_list, errors

    errors.append(f"unsupported field type '{spec.field_type}'.")
    return value, errors


def _should_store_value(spec: ManualFieldSpec, value: Any, raw: Any) -> bool:
    if raw is not None:
        return True
    if spec.default is not None:
        return True
    if spec.required:
        return True
    return value not in (None, "", [], {})
