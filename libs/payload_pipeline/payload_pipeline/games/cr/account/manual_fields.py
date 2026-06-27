"""Clash Royale manual entry field specifications.

The fields are selected by checking Eldorado and GameBoost templates together,
then asking only for the minimum game data needed to build all
marketplace-specific payloads.
"""

from __future__ import annotations

from ....core.manual_fields import ManualFieldSpec, manual_field_registry

CR_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="king_level",
        label="King Tower Level",
        field_type="number",
        required=True,
        min_value=0,
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
        key="arena",
        label="Arena Level",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
    ManualFieldSpec(
        key="evolution_count",
        label="Evolution Count",
        field_type="number",
        required=False,
        min_value=0,
        group="Account Data",
    ),
]

manual_field_registry.register("clash-royale", CR_MANUAL_FIELDS)
