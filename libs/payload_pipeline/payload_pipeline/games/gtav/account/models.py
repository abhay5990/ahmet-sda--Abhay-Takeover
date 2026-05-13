"""Resolved models for the GTA V slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class GtavResolvedAccount(ResolvedAccountBase):
    """Single resolved GTA V account after source normalization."""

    main_platform: str = ""
    level: int = 0
    cash_amount: int = 0
    cash_unit: str = "Million"
    cars_count: int = 0
    tags: list[str] = field(default_factory=list)

    has_dual_characters: bool = False

    security_email: str = ""
    security_email_password: str = ""
    security_email_login_link: str = ""
    birthday: str = ""
    email_backup_codes: str = ""

    has_email_access: bool = False
    title: str = "GTA V Account"
    description: str = ""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "main_platform": FieldMeta("Primary platform.", "PC"),
        "level": FieldMeta("GTA Online level.", 250),
        "cash_amount": FieldMeta("In-game cash amount.", 500),
        "cash_unit": FieldMeta("Cash unit label.", "Million"),
        "cars_count": FieldMeta("Owned vehicle count.", 120),
        "tags": FieldMeta("Account tags.", ["Modded", "High Level"]),
        "has_dual_characters": FieldMeta("Has two online characters.", True),
        "has_email_access": FieldMeta("Email access status.", True),
        "title": FieldMeta("Listing title override.", "GTA V Account"),
        "description": FieldMeta("Listing description override.", ""),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
