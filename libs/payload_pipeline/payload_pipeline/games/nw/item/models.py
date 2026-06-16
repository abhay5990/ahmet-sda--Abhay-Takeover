"""Resolved models for the New World item slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class NwResolvedItem(ResolvedAccountBase):
    """A New World listing posted as an item on GameBoost.

    Uses ``ResolvedAccountBase`` so that credentials flow through the
    standard pipeline and appear in ``delivery_instructions``.
    """

    region: str = ""
    """Destination region for the item listing (e.g. 'North America', 'Europe')."""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "region": FieldMeta("GameBoost item server/region.", "North America"),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
