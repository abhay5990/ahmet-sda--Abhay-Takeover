"""Domain types for the password changer service."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChangeStatus(str, Enum):
    """Outcome of a single password change attempt."""

    SUCCESS = "success"
    WRONG_PASSWORD = "wrong_password"       # 401 — current password incorrect
    NOT_FOUND = "not_found"                 # 404 — email doesn't exist
    VALIDATION_ERROR = "validation_error"   # 400 — 2FA, bad format, etc.
    RATE_LIMITED = "rate_limited"            # 403 rate limit
    FORBIDDEN = "forbidden"                 # 403 non-rate-limit
    SERVER_ERROR = "server_error"           # 500
    NETWORK_ERROR = "network_error"         # connection/timeout
    UNKNOWN = "unknown"


class ChangeProvider(str, Enum):
    """Supported email providers for password change."""

    FIRSTMAIL = "firstmail"
    # Future: RAMBLER = "rambler"


@dataclass(slots=True)
class PasswordChangeResult:
    """Result of a single password change attempt."""

    email: str
    status: ChangeStatus
    provider: ChangeProvider
    new_password: str = ""          # only populated on SUCCESS
    detail: str = ""
    elapsed_ms: int = 0
    owned_product_id: int | None = None
    db_updated: bool = False        # True if OwnedProduct.email_password was persisted

    @property
    def success(self) -> bool:
        return self.status == ChangeStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "status": self.status.value,
            "provider": self.provider.value,
            "new_password": self.new_password,
            "detail": self.detail,
            "elapsed_ms": self.elapsed_ms,
            "owned_product_id": self.owned_product_id,
            "db_updated": self.db_updated,
        }
