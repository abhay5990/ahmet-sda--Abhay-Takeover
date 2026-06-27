"""Rainbow Six Siege manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_CURRENT_RANK_OPTIONS = (
    FieldOption("ranked-ready", "Ranked Ready (Unranked)"),
    FieldOption("copper", "Copper"),
    FieldOption("bronze", "Bronze"),
    FieldOption("silver", "Silver"),
    FieldOption("gold", "Gold"),
    FieldOption("platinum", "Platinum"),
    FieldOption("emerald", "Emerald"),
    FieldOption("diamond", "Diamond"),
    FieldOption("champions", "Champions"),
)

_PREVIOUS_RANK_OPTIONS = (
    FieldOption("previous-unraked", "Unranked"),
    FieldOption("previous-copper", "Copper"),
    FieldOption("previous-bronze", "Bronze"),
    FieldOption("previous-silver", "Silver"),
    FieldOption("previous-gold", "Gold"),
    FieldOption("previous-platinum", "Platinum"),
    FieldOption("previous-emerald", "Emerald"),
    FieldOption("previous-diamond", "Diamond"),
    FieldOption("previous-champion", "Champion"),
)

_GAME_PURCHASED_OPTIONS = (
    FieldOption("purchased-yes", "Yes"),
    FieldOption("purchased-no", "No"),
)

_RANKED_UNLOCKED_OPTIONS = (
    FieldOption("ranked-unlocked-yes", "Yes"),
    FieldOption("ranked-unlocked-no", "No"),
)

R6_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="current_rank",
        label="Current Rank",
        field_type="select",
        required=False,
        options=_CURRENT_RANK_OPTIONS,
        default="ranked-ready",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="previous_rank",
        label="Previous Rank",
        field_type="select",
        required=False,
        options=_PREVIOUS_RANK_OPTIONS,
        default="previous-unraked",
        group="Account Data",
    ),
    ManualFieldSpec(
        key="game_purchased",
        label="Game Purchased",
        field_type="select",
        required=False,
        options=_GAME_PURCHASED_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="ranked_unlocked",
        label="Ranked Unlocked",
        field_type="select",
        required=False,
        options=_RANKED_UNLOCKED_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="operators",
        label="Operators",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="renown",
        label="Renown",
        field_type="number",
        required=False,
        min_value=0,
        group="Currency",
    ),
    ManualFieldSpec(
        key="black_ice_skins",
        label="Black Ice Skins",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
]

manual_field_registry.register("rainbow-six-siege", R6_MANUAL_FIELDS)
