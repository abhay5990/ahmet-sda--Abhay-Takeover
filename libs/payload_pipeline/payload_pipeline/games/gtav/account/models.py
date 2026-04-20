"""Resolved models for the GTA V slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class GtavResolvedAccount(ResolvedAccountBase):
    """Single resolved GTA V account after source normalization."""

    main_platform: str = ""
    level: int = 0
    cash_amount: int = 0
    cash_unit: str = "Million"
    cars_count: int = 0
    tags: list[str] = field(default_factory=list)

    security_email: str = ""
    security_email_password: str = ""
    security_email_login_link: str = ""
    birthday: str = ""
    email_backup_codes: str = ""

    eldorado_price: float = 0.0
    gameboost_price: float = 0.0
    playerauctions_price: float = 0.0

    has_email_access: bool = False
    title: str = "GTA V Account"
    description: str = ""
