"""Fortnite manual entry field specifications.

Fields derived from Eldorado attribute templates, GameBoost fields,
and the FortniteResolvedAccount model.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_LINKABLE_OPTIONS = (
    FieldOption("yes", "Yes"),
    FieldOption("no", "No"),
)

_ACCOUNT_TAG_OPTIONS = (
    FieldOption("og_account", "OG Account"),
    FieldOption("original_email", "Original Email"),
    FieldOption("stacked", "Stacked"),
    FieldOption("save_the_world", "Save The World"),
    FieldOption("battle_royale", "Battle Royale"),
    FieldOption("the_crew", "The Crew"),
)

FN_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="level",
        label="Account Level",
        field_type="number",
        required=True,
        min_value=1,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="skin_count",
        label="Outfits / Skins",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="pickaxe_count",
        label="Pickaxes",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="dance_count",
        label="Emotes",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="glider_count",
        label="Gliders",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="backpack_count",
        label="Back Blings",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="wrap_count",
        label="Wraps",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="spray_count",
        label="Sprays",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory Counts",
    ),
    ManualFieldSpec(
        key="v_bucks",
        label="V-Bucks",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="psn_linkable",
        label="PSN Linkable",
        field_type="select",
        required=False,
        options=_LINKABLE_OPTIONS,
        default="no",
        group="Linkability",
    ),
    ManualFieldSpec(
        key="xbox_linkable",
        label="Xbox Linkable",
        field_type="select",
        required=False,
        options=_LINKABLE_OPTIONS,
        default="no",
        group="Linkability",
    ),
    ManualFieldSpec(
        key="account_tags",
        label="Account Tags",
        field_type="multiselect",
        required=False,
        options=_ACCOUNT_TAG_OPTIONS,
        group="Tags",
    ),
]

manual_field_registry.register("fortnite", FN_MANUAL_FIELDS)
