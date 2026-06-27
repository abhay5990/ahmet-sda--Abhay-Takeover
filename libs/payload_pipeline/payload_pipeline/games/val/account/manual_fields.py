"""Valorant manual entry field specifications.

The fields are selected by checking Eldorado, GameBoost, and PlayerAuctions
templates together, then asking only for the minimum game data needed to build
all marketplace-specific payloads.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_REGION_OPTIONS = (
    FieldOption("na", "North America"),
    FieldOption("eu", "Europe"),
    FieldOption("la", "LATAM"),
    FieldOption("br", "Brazil"),
    FieldOption("ap", "Asia Pacific"),
    FieldOption("kr", "Korea"),
    FieldOption("tr", "Turkey"),
)

_RANK_OPTIONS = (
    FieldOption("unranked", "Unranked"),
    FieldOption("iron", "Iron"),
    FieldOption("bronze", "Bronze"),
    FieldOption("silver", "Silver"),
    FieldOption("gold", "Gold"),
    FieldOption("platinum", "Platinum"),
    FieldOption("diamond", "Diamond"),
    FieldOption("ascendant", "Ascendant"),
    FieldOption("immortal", "Immortal"),
    FieldOption("radiant", "Radiant"),
)

_TAG_OPTIONS = (
    FieldOption("ranked_ready", "Ranked Ready"),
    FieldOption("has_email", "Has Original Email"),
    FieldOption("smurf", "Smurf Account"),
    FieldOption("rare_skins", "Rare Skins"),
    FieldOption("full_agents", "All Agents Unlocked"),
)

VALORANT_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="region",
        label="Region",
        field_type="select",
        required=True,
        options=_REGION_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="level",
        label="Level",
        field_type="number",
        required=True,
        min_value=1,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="current_rank",
        label="Current Rank",
        field_type="select",
        required=False,
        options=_RANK_OPTIONS,
        default="unranked",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="peak_rank",
        label="Peak Rank",
        field_type="select",
        required=False,
        options=_RANK_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="valorant_points",
        label="Valorant Points (VP)",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="radianite_points",
        label="Radianite Points",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="agent_count",
        label="Agent Count",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory Counts",
        help_text="Used for Eldorado agent range and content.",
    ),
    ManualFieldSpec(
        key="weapon_skin_count",
        label="Weapon Skin Count",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory Counts",
        help_text="Used for Eldorado weapon skin range and content.",
    ),
    ManualFieldSpec(
        key="knife_count",
        label="Knife Count",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory Counts",
        help_text="Used for Eldorado knife range.",
    ),
    ManualFieldSpec(
        key="inventory_value",
        label="Inventory Value (VP)",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory Counts",
        help_text="Used for Eldorado spent points range.",
    ),
    ManualFieldSpec(
        key="account_tags",
        label="Account Tags",
        field_type="multiselect",
        required=False,
        options=_TAG_OPTIONS,
        group="Tags",
    ),
]

manual_field_registry.register("valorant", VALORANT_MANUAL_FIELDS)
