"""Clash of Clans manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_RANK_OPTIONS = (
    FieldOption("rank-unranked", "Unranked"),
    FieldOption("rank-skeleton", "Skeleton"),
    FieldOption("rank-barbarian", "Barbarian"),
    FieldOption("rank-archer", "Archer"),
    FieldOption("rank-wizard", "Wizard"),
    FieldOption("rank-valkyrie", "Valkyrie"),
    FieldOption("rank-witch", "Witch"),
    FieldOption("rank-golem", "Golem"),
    FieldOption("rank-pekka", "P.E.K.K.A"),
    FieldOption("rank-titan", "Titan"),
    FieldOption("rank-dragon", "Dragon"),
    FieldOption("rank-electro", "Electro"),
    FieldOption("rank-legend", "Legend"),
)

_MAXED_ACCOUNT_OPTIONS = (
    FieldOption("maxed-yes", "Yes"),
    FieldOption("maxed-no", "No"),
)

COC_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="town_hall",
        label="Town Hall Level",
        field_type="number",
        required=True,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="current_rank",
        label="Current Rank",
        field_type="select",
        required=False,
        options=_RANK_OPTIONS,
        default="rank-unranked",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="maxed_account",
        label="Maxed Account",
        field_type="select",
        required=False,
        options=_MAXED_ACCOUNT_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="gems",
        label="Gems",
        field_type="number",
        required=False,
        min_value=0,
        group="Currency",
    ),
]

manual_field_registry.register("clash-of-clans", COC_MANUAL_FIELDS)
