"""Resolved models for the New World account slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class NwResolvedAccount(ResolvedAccountBase):
    """Single resolved New World account after source normalization."""

    region: str = ""
    """Selected region: US-East, US-West, AP Southeast, SA East, EU-Central."""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "region": FieldMeta("Account region (US-East / US-West / EU-Central / etc.).", "US-East"),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
