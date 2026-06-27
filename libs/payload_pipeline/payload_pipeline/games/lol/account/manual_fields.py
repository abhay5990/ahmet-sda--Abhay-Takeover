"""League of Legends manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_SERVER_OPTIONS = (
    FieldOption("na", "North America"),
    FieldOption("euw", "Europe West"),
    FieldOption("eune", "Europe Nordic & East"),
    FieldOption("br", "Brazil"),
    FieldOption("la1", "Latin America North"),
    FieldOption("la2", "Latin America South"),
    FieldOption("oce", "Oceania"),
    FieldOption("tr", "Turkey"),
    FieldOption("jp", "Japan"),
    FieldOption("kr", "Korea"),
    FieldOption("sg", "Singapore"),
    FieldOption("ph", "Philippines"),
    FieldOption("tw", "Taiwan"),
    FieldOption("me", "Middle East"),
)

_CURRENT_RANK_OPTIONS = (
    FieldOption("unranked", "Unranked"),
    FieldOption("iron", "Iron"),
    FieldOption("bronze", "Bronze"),
    FieldOption("silver", "Silver"),
    FieldOption("gold", "Gold"),
    FieldOption("platinum", "Platinum"),
    FieldOption("emerald", "Emerald"),
    FieldOption("diamond", "Diamond"),
    FieldOption("current-master", "Master"),
    FieldOption("current-grandmaster", "Grandmaster"),
    FieldOption("current-challenger", "Challenger"),
)

_PREVIOUS_RANK_OPTIONS = (
    FieldOption("previous-unranked", "Unranked"),
    FieldOption("previous-iron", "Iron"),
    FieldOption("previous-bronze", "Bronze"),
    FieldOption("previous-silver", "Silver"),
    FieldOption("previous-gold", "Gold"),
    FieldOption("previous-platinum", "Platinum"),
    FieldOption("previous-emerald", "Emerald"),
    FieldOption("previous-diamond", "Diamond"),
    FieldOption("previous-master", "Master"),
    FieldOption("previous-grandmaster", "Grandmaster"),
    FieldOption("previous-challenger", "Challenger"),
)

_RANKED_READY_OPTIONS = (
    FieldOption("ready-yes", "Yes"),
    FieldOption("ready-no", "No"),
)

LOL_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="server",
        label="Server",
        field_type="select",
        required=True,
        options=_SERVER_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="current_rank",
        label="Current Rank",
        field_type="select",
        required=False,
        options=_CURRENT_RANK_OPTIONS,
        default="unranked",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="previous_rank",
        label="Previous Rank",
        field_type="select",
        required=False,
        options=_PREVIOUS_RANK_OPTIONS,
        default="previous-unranked",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="ranked_ready",
        label="Ranked Ready",
        field_type="select",
        required=False,
        options=_RANKED_READY_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="champion_count",
        label="Champion Count",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="skins",
        label="Skins",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="blue_essence",
        label="Blue Essence",
        field_type="number",
        required=False,
        min_value=0,
        group="Currency",
    ),
    ManualFieldSpec(
        key="riot_points",
        label="Riot Points",
        field_type="number",
        required=False,
        min_value=0,
        group="Currency",
    ),
]

manual_field_registry.register("league-of-legends", LOL_MANUAL_FIELDS)
