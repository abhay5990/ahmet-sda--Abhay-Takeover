"""Roblox manual entry field specifications."""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_ACCOUNT_TYPE_OPTIONS = (
    FieldOption("type-inventory", "Inventory"),
    FieldOption("type-robux-account", "Robux Account"),
    FieldOption("type-limiteds", "Limiteds"),
    FieldOption("type-korblox", "Korblox"),
    FieldOption("type-headless", "Headless"),
    FieldOption("type-offsale", "Offsale"),
    FieldOption("type-old-account", "Old Account"),
    FieldOption("type-4-letter", "4-Letter Username"),
    FieldOption("type-rare-username", "Rare Username"),
    FieldOption("type-other", "Other"),
)

_GAME_OPTIONS = (
    FieldOption("game-blox-fruits", "Blox Fruits"),
    FieldOption("game-adopt-me", "Adopt Me"),
    FieldOption("game-grow-a-garden", "Grow a Garden"),
    FieldOption("game-anime-vanguards", "Anime Vanguards"),
    FieldOption("game-rivals", "Rivals"),
    FieldOption("game-fisch", "Fisch"),
    FieldOption("game-jailbreak", "Jailbreak"),
    FieldOption("game-dead-rails", "Dead Rails"),
    FieldOption("game-king-legacy", "King Legacy"),
    FieldOption("game-pet-simulator-99", "Pet Simulator 99"),
    FieldOption("game-murder-mystery-2", "Murder Mystery 2"),
    FieldOption("game-da-hood", "Da Hood"),
    FieldOption("game-royale-high", "Royale High"),
    FieldOption("game-brookhaven-rp", "Brookhaven RP"),
    FieldOption("game-bedwars", "Bedwars"),
    FieldOption("game-bee-swarm-simulator", "Bee Swarm Simulator"),
    FieldOption("game-grand-piece-online", "Grand Piece Online"),
    FieldOption("game-bloxburg", "Bloxburg"),
    FieldOption("game-other", "Other"),
)

_AGE_VERIFIED_OPTIONS = (
    FieldOption("verified-yes", "Yes"),
    FieldOption("verified-no", "No"),
)

ROBLOX_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="account_type",
        label="Account Type",
        field_type="select",
        required=True,
        options=_ACCOUNT_TYPE_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="game",
        label="Primary Game",
        field_type="select",
        required=False,
        options=_GAME_OPTIONS,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="inventory_value",
        label="Inventory Value (RAP)",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="offsale_items",
        label="Offsale Items",
        field_type="number",
        required=False,
        min_value=0,
        group="Inventory",
    ),
    ManualFieldSpec(
        key="robux_value",
        label="Robux Balance",
        field_type="number",
        required=False,
        min_value=0,
        group="Currency",
    ),
    ManualFieldSpec(
        key="age_verified",
        label="Age Verified",
        field_type="select",
        required=False,
        options=_AGE_VERIFIED_OPTIONS,
        group="Account Data",
    ),
]

manual_field_registry.register("roblox", ROBLOX_MANUAL_FIELDS)
