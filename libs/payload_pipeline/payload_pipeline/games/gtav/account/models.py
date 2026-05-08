"""Resolved models for the GTA V slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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

    has_dual_characters: bool = False

    security_email: str = ""
    security_email_password: str = ""
    security_email_login_link: str = ""
    birthday: str = ""
    email_backup_codes: str = ""

    has_email_access: bool = False
    title: str = "GTA V Account"
    description: str = ""

    credential_extras: dict[str, Any] = field(default_factory=dict)
    """Platform-specific credential fields (steam_id, rock_id, dob, etc.)
    consumed by :func:`~.credentials.format_platform_credentials`."""
