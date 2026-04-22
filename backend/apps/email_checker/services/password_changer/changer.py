"""Core password changer service.

Coordinates:
- Password generation (secure random)
- FirstMail SDK client call
- OwnedProduct.email_password persistence
"""

from __future__ import annotations

import secrets
import string
import time

from apis_sdk.clients.services.firstmail.facade import FirstMailFacade
from apis_sdk.clients.services.firstmail.models import ChangePasswordStatus

from .types import ChangeProvider, ChangeStatus, PasswordChangeResult


# Map SDK status → service status
_STATUS_MAP: dict[ChangePasswordStatus, ChangeStatus] = {
    ChangePasswordStatus.SUCCESS: ChangeStatus.SUCCESS,
    ChangePasswordStatus.WRONG_PASSWORD: ChangeStatus.WRONG_PASSWORD,
    ChangePasswordStatus.NOT_FOUND: ChangeStatus.NOT_FOUND,
    ChangePasswordStatus.VALIDATION_ERROR: ChangeStatus.VALIDATION_ERROR,
    ChangePasswordStatus.RATE_LIMITED: ChangeStatus.RATE_LIMITED,
    ChangePasswordStatus.FORBIDDEN: ChangeStatus.FORBIDDEN,
    ChangePasswordStatus.SERVER_ERROR: ChangeStatus.SERVER_ERROR,
    ChangePasswordStatus.UNKNOWN: ChangeStatus.UNKNOWN,
}


def generate_password(length: int = 14) -> str:
    """Generate a cryptographically secure random password.

    Format: 8 lowercase + 1 uppercase + '!' + 4 digits = 14 chars default.
    Uses secrets module (CSPRNG) instead of random.
    """
    lower = ''.join(secrets.choice(string.ascii_lowercase) for _ in range(length - 6))
    upper = secrets.choice(string.ascii_uppercase)
    digits = ''.join(secrets.choice(string.digits) for _ in range(4))
    special = '!'
    return f"{lower}{upper}{special}{digits}"


class EmailPasswordChanger:
    """Changes email passwords via FirstMail API and persists results."""

    def __init__(self, facade: FirstMailFacade) -> None:
        self._facade = facade

    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str | None = None,
        *,
        proxy_url: str | None = None,
    ) -> PasswordChangeResult:
        """Change password for a single email. Does NOT touch DB."""
        if new_password is None:
            new_password = generate_password()

        start = time.monotonic()
        api_result = self._facade.change_password(
            email, current_password, new_password, proxy_url=proxy_url,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Rate limit / network error — ApiResult.ok is False
        if not api_result.ok:
            error = api_result.error
            if error and error.category.value == "rate_limit":
                status = ChangeStatus.RATE_LIMITED
            elif error and error.category.value == "network":
                status = ChangeStatus.NETWORK_ERROR
            else:
                status = ChangeStatus.UNKNOWN
            return PasswordChangeResult(
                email=email,
                status=status,
                provider=ChangeProvider.FIRSTMAIL,
                detail=error.message if error else "Unknown error",
                elapsed_ms=elapsed_ms,
            )

        # Successful API call — check the response status
        resp = api_result.data
        mapped_status = _STATUS_MAP.get(resp.status, ChangeStatus.UNKNOWN)

        return PasswordChangeResult(
            email=email,
            status=mapped_status,
            provider=ChangeProvider.FIRSTMAIL,
            new_password=new_password if mapped_status == ChangeStatus.SUCCESS else "",
            detail=resp.error_message,
            elapsed_ms=elapsed_ms,
        )

    def change_and_persist(
        self,
        owned_product,
        new_password: str | None = None,
        *,
        proxy_url: str | None = None,
    ) -> PasswordChangeResult:
        """Change password + update OwnedProduct.email_password on success."""
        result = self.change_password(
            email=owned_product.email,
            current_password=owned_product.email_password,
            new_password=new_password,
            proxy_url=proxy_url,
        )
        result.owned_product_id = owned_product.id

        if result.success:
            owned_product.email_password = result.new_password
            owned_product.save(update_fields=["email_password", "updated_at"])
            result.db_updated = True

        return result
