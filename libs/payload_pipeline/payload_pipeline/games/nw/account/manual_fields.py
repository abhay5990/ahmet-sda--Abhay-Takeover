"""New World manual entry field specifications.

The fields are selected by checking Eldorado and GameBoost templates together,
then asking only for the minimum game data needed to build all
marketplace-specific payloads.
"""

from __future__ import annotations

from ....core.manual_fields import FieldOption, ManualFieldSpec, manual_field_registry

_REGION_OPTIONS = (
    FieldOption("US - East", "US - East"),
    FieldOption("US - West", "US - West"),
    FieldOption("AP Southeast", "AP Southeast"),
    FieldOption("SA East", "SA East"),
    FieldOption("EU - Central", "EU - Central"),
)

NW_MANUAL_FIELDS: list[ManualFieldSpec] = [
    ManualFieldSpec(
        key="region",
        label="Region",
        field_type="select",
        required=True,
        options=_REGION_OPTIONS,
        group="Account Data",
    ),
]

manual_field_registry.register("new-world", NW_MANUAL_FIELDS)
