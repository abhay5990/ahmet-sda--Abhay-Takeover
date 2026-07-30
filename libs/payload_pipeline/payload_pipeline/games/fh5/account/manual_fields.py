"""Forza Horizon 5 manual entry field specifications.

The fields are selected by checking Eldorado and GameBoost templates together,
then asking only for the minimum game data needed to build all
marketplace-specific payloads.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

# Values MUST match the Forza H5 platform GameVariant source keys (PC / Xbox /
# PS5) so the selection resolves to the Eldorado tradeEnvironmentId (0/1/2).
# Steam / Microsoft Store accounts are "PC" on Eldorado.
_PLATFORM_OPTIONS = (
    FieldOption("PC", "PC (Steam / Microsoft Store)"),
    FieldOption("Xbox", "Xbox"),
    FieldOption("PS5", "PlayStation (PS5)"),
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
