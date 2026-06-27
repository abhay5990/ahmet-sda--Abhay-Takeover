"""Rust manual entry field specifications.

The fields are selected by checking Eldorado and GameBoost templates together,
then asking only for the minimum game data needed to build all
marketplace-specific payloads.

Eldorado needs range-bucketed attributes (hours, skins, steam level, premium
status) which are derived from the integer values entered here.
GameBoost needs the raw integers directly.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_PLATFORM_OPTIONS = (
    FieldOption("PC", "PC"),
    FieldOption("PlayStation", "PlayStation"),
    FieldOption("Xbox", "Xbox"),
)

_PREMIUM_STATUS_OPTIONS = (
    FieldOption("Yes", "Yes"),
    FieldOption("No", "No"),
)

RUST_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="platform",
        label="Platform",
        field_type="select",
        required=True,
        options=_PLATFORM_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="premium_status",
        label="Premium Status",
        field_type="select",
        required=False,
        options=_PREMIUM_STATUS_OPTIONS,
        default="No",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="real_hours",
        label="Real Hours Played",
        field_type="number",
        required=True,
        min_value=0,
        group="Account Data",
        help_text="Actual hours played. Used for Eldorado hours range and GameBoost.",
    ),
    ManualFieldSpec(
        key="skins_count",
        label="Skins Count",
        field_type="number",
        required=True,
        min_value=0,
        group="Account Data",
        help_text="Number of skins. Used for Eldorado skins range and GameBoost.",
    ),
    ManualFieldSpec(
        key="steam_level",
        label="Steam Account Level",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
        help_text="Steam account level. Used for Eldorado steam level range.",
    ),
]

manual_field_registry.register("rust", RUST_MANUAL_FIELDS)
