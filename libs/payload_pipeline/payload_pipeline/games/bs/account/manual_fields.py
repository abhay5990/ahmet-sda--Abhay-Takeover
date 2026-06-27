"""Brawl Stars manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_RANK_OPTIONS = (
    FieldOption("rank-bronze1", "Bronze I"),
    FieldOption("rank-bronze2", "Bronze II"),
    FieldOption("rank-bronze3", "Bronze III"),
    FieldOption("rank-silver1", "Silver I"),
    FieldOption("rank-silver2", "Silver II"),
    FieldOption("rank-silver3", "Silver III"),
    FieldOption("rank-gold1", "Gold I"),
    FieldOption("rank-gold2", "Gold II"),
    FieldOption("rank-gold3", "Gold III"),
    FieldOption("rank-diamond1", "Diamond I"),
    FieldOption("rank-diamond2", "Diamond II"),
    FieldOption("rank-diamond3", "Diamond III"),
    FieldOption("rank-mythic1", "Mythic I"),
    FieldOption("rank-mythic2", "Mythic II"),
    FieldOption("rank-mythic3", "Mythic III"),
    FieldOption("rank-legendary1", "Legendary I"),
    FieldOption("rank-legendary2", "Legendary II"),
    FieldOption("rank-legendary3", "Legendary III"),
    FieldOption("rank-masters1", "Masters I"),
    FieldOption("rank-masters2", "Masters II"),
    FieldOption("rank-masters3", "Masters III"),
    FieldOption("rank-pro", "Pro"),
)

BS_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="rank",
        label="Rank",
        field_type="select",
        required=False,
        options=_RANK_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="trophies",
        label="Trophies",
        field_type="number",
        required=True,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="brawlers",
        label="Brawlers",
        field_type="number",
        required=True,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="maxed_brawlers",
        label="Maxed Brawlers",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="skins",
        label="Skins",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="prestige",
        label="Prestige",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="hypercharge",
        label="Hypercharges",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="buffies",
        label="Buffies",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
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

manual_field_registry.register("brawl-stars", BS_MANUAL_FIELDS)
