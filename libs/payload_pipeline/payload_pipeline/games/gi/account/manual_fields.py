"""Genshin Impact manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_REGION_OPTIONS = (
    FieldOption("na", "NA (America)"),
    FieldOption("eu", "EU (Europe)"),
    FieldOption("asia", "Asia"),
    FieldOption("sar", "SAR (TW/HK/MO)"),
)

_ACCOUNT_TYPE_OPTIONS = (
    FieldOption("type-reroll", "Reroll"),
    FieldOption("type-rolled", "Rolled"),
    FieldOption("type-handleveled", "Hand-Leveled"),
    FieldOption("type-other", "Other"),
)

GI_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="region",
        label="Region",
        field_type="select",
        required=True,
        options=_REGION_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="account_type",
        label="Account Type",
        field_type="select",
        required=False,
        options=_ACCOUNT_TYPE_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="adventure_rank",
        label="Adventure Rank",
        field_type="number",
        required=True,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="characters",
        label="5-Star Characters",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="legendary_weapons",
        label="5-Star Weapons",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="events_count",
        label="Limited Events",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="primogems",
        label="Primogems",
        field_type="number",
        required=False,
        min_value=0,
        group="Currency",
    ),
]

manual_field_registry.register("genshin-impact", GI_MANUAL_FIELDS)
