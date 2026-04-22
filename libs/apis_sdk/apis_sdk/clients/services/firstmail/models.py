"""
FirstMail API response models.

These represent the raw API responses from FirstMail.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ChangePasswordStatus(str, Enum):
    """Categorized result of a password change attempt."""

    SUCCESS = "success"
    WRONG_PASSWORD = "wrong_password"       # 401
    NOT_FOUND = "not_found"                 # 404
    VALIDATION_ERROR = "validation_error"   # 400 (2FA, missing fields, etc.)
    RATE_LIMITED = "rate_limited"            # 403 with rate limit message
    SERVER_ERROR = "server_error"           # 500
    FORBIDDEN = "forbidden"                 # 403 non-rate-limit
    UNKNOWN = "unknown"


class ChangePasswordResponse(BaseModel):
    """Parsed result of a password change API call."""

    status: ChangePasswordStatus
    success: bool
    email: str
    http_status: int = 0
    error_message: str = ""

    model_config = {"frozen": True}
