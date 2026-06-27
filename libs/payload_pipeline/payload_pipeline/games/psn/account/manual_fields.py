"""PlayStation manual entry field specifications.

PSN accounts have no game-specific marketplace attributes.
Registration ensures the API recognizes the game for manual entry.
"""

from __future__ import annotations

from ....core.manual_fields import ManualFieldSpec, manual_field_registry

PSN_MANUAL_FIELDS: list[ManualFieldSpec] = []

manual_field_registry.register("playstation", PSN_MANUAL_FIELDS)
