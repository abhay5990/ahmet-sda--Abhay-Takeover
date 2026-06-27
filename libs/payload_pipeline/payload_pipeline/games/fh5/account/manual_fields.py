"""Forza Horizon 5 manual entry field specifications.

The fields are selected by checking Eldorado and GameBoost templates together,
then asking only for the minimum game data needed to build all
marketplace-specific payloads.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_PLATFORM_OPTIONS = (
    FieldOption("Steam", "Steam"),
    FieldOption("Xbox", "Xbox"),
    FieldOption("PlayStation", "PlayStation"),
    FieldOption("PC", "PC"),
)

_EDITION_OPTIONS = (
    FieldOption("Standard", "Standard"),
    FieldOption("Deluxe", "Deluxe"),
    FieldOption("Premium", "Premium"),
)

FH5_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="platform",
        label="Platform",
        field_type="select",
        required=True,
        options=_PLATFORM_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="edition",
        label="Edition",
        field_type="select",
        required=False,
        options=_EDITION_OPTIONS,
        default="Standard",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="cars_count",
        label="Cars Count",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="credits_count",
        label="Credits Count",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
]

manual_field_registry.register("forza-horizon-5", FH5_MANUAL_FIELDS)
