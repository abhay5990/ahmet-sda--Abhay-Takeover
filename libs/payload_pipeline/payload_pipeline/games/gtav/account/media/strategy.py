"""Static media strategy for GTA V accounts."""

from __future__ import annotations

from pathlib import Path

from .....core.contracts import PipelineRequest
from .....shared.static_media import StaticAccountMediaStrategy, StaticMediaSpec
from ..models import GtavResolvedAccount

_RESOURCE_PATH = Path(__file__).resolve().parent.parent / "resources" / "media" / "account.png"


class GtavMediaStrategy(StaticAccountMediaStrategy):
    """Prepare the bundled GTA V account image."""

    def __init__(self) -> None:
        super().__init__(
            StaticMediaSpec(
                resource_path=_RESOURCE_PATH,
            )
        )

    def prepare(self, subject: GtavResolvedAccount, request: PipelineRequest) -> list[str]:
        return super().prepare(subject, request)
