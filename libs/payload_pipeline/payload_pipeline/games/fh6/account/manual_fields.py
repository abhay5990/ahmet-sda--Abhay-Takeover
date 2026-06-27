"""Forza Horizon 6 manual entry field specifications.

The fields are selected by checking Eldorado and GameBoost templates together,
then asking only for the minimum game data needed to build all
marketplace-specific payloads.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_PLATFORM_OPTIONS = (
    FieldOption("PC", "PC"),
    FieldOption("PS5", "PS5"),
    FieldOption("Xbox", "Xbox"),
)

_ALL_CARS_OPTIONS = (
    FieldOption("Yes", "Yes"),
    FieldOption("No", "No"),
)

FH6_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="platform",
        label="Platform",
        field_type="select",
        required=True,
        options=_PLATFORM_OPTIONS,
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
    ManualFieldSpec(
        key="all_cars",
        label="All Cars",
        field_type="select",
        required=False,
        options=_ALL_CARS_OPTIONS,
        default="No",
        group="Account Data",
    ),
]

manual_field_registry.register("forza-horizon-6", FH6_MANUAL_FIELDS)
