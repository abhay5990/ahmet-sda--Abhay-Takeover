"""GTA V manual entry field specifications.

GTA V uses a legacy hardcoded manual flow with platform-specific credential
handling. Game-specific fields (platform, level, cash, cars, tags) are
managed via the existing GTA manual UI. This registration is for API
consistency; the frontend uses the legacy form for GTA V.
"""

from __future__ import annotations

from ....core.manual_fields import ManualFieldSpec, manual_field_registry

GTAV_MANUAL_FIELDS: list[ManualFieldSpec] = []

manual_field_registry.register("grand-theft-auto-5", GTAV_MANUAL_FIELDS)
