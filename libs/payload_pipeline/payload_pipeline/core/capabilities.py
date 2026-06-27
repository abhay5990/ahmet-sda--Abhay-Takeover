"""Media capability declarations for game strategies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaCapabilities:
    """Declarative media capabilities for a game's media strategy.

    Used by the Django layer to determine which UI options to show
    (e.g. "Auto Generated" button, gallery/override picker).

    Attributes:
        auto_generate_manual: Strategy can produce images from minimal
            manual-entry data (e.g. GTA V card from level/cash/platform).
        supports_override: Strategy honours ``MEDIA_OVERRIDE_PATH`` so
            the user can select a custom image from the gallery.
    """

    auto_generate_manual: bool = False
    supports_override: bool = True


# Shared defaults — import these instead of creating new instances.
OVERRIDE_ONLY = MediaCapabilities(auto_generate_manual=False, supports_override=True)
AUTO_GEN_AND_OVERRIDE = MediaCapabilities(auto_generate_manual=True, supports_override=True)
NO_MEDIA = MediaCapabilities(auto_generate_manual=False, supports_override=False)
