"""Resolved models for the Forza Horizon 6 slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class Fh6ResolvedAccount(ResolvedAccountBase):
    """Single resolved Forza Horizon 6 account after source normalization."""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
