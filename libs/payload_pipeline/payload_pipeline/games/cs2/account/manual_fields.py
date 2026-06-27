"""Counter-Strike 2 manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_PRIME_STATUS_OPTIONS = (
    FieldOption("active-prime", "Active Prime"),
    FieldOption("non-prime", "Non-Prime"),
)

_VETERAN_COIN_OPTIONS = (
    FieldOption("5year-coin", "5 Year Coin"),
    FieldOption("10year-coin", "10 Year Coin"),
    FieldOption("other-coin", "None / Other"),
)

_ESEA_RATING_OPTIONS = (
    FieldOption("esea-d-", "D-"),
    FieldOption("esea-d", "D"),
    FieldOption("esea-dplus", "D+"),
    FieldOption("esea-c-", "C-"),
    FieldOption("esea-c", "C"),
    FieldOption("esea-cplus", "C+"),
    FieldOption("esea-b-", "B-"),
    FieldOption("esea-b", "B"),
    FieldOption("esea-bplus", "B+"),
    FieldOption("esea-a-", "A-"),
    FieldOption("esea-a", "A"),
    FieldOption("esea-aplus", "A+"),
    FieldOption("esea-g", "G"),
    FieldOption("esea-s", "S"),
    FieldOption("esea-other", "None / Other"),
)

_FACEIT_LEVEL_OPTIONS = (
    FieldOption("faceit-1", "Level 1"),
    FieldOption("faceit-2", "Level 2"),
    FieldOption("faceit-3", "Level 3"),
    FieldOption("faceit-4", "Level 4"),
    FieldOption("faceit-5", "Level 5"),
    FieldOption("faceit-6", "Level 6"),
    FieldOption("faceit-7", "Level 7"),
    FieldOption("faceit-8", "Level 8"),
    FieldOption("faceit-9", "Level 9"),
    FieldOption("faceit-10", "Level 10"),
    FieldOption("faceit-other", "None / Other"),
)

CS2_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="premier_rating",
        label="Premier Rating",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
        help_text="Premier ELO rating (0 = unrated).",
    ),
    ManualFieldSpec(
        key="prime_status",
        label="Prime Status",
        field_type="select",
        required=True,
        options=_PRIME_STATUS_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="medals",
        label="Medals",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
        help_text="Number of service medals.",
    ),
    ManualFieldSpec(
        key="veteran_coin",
        label="Veteran Coin",
        field_type="select",
        required=False,
        options=_VETERAN_COIN_OPTIONS,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="esea_rating",
        label="ESEA Rating",
        field_type="select",
        required=False,
        options=_ESEA_RATING_OPTIONS,
        group="Competitive",
    ),
    ManualFieldSpec(
        key="faceit_level",
        label="Faceit Level",
        field_type="select",
        required=False,
        options=_FACEIT_LEVEL_OPTIONS,
        group="Competitive",
    ),
]

manual_field_registry.register("counter-strike-2", CS2_MANUAL_FIELDS)
