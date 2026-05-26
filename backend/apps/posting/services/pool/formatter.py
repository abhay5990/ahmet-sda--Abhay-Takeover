"""Format OwnedProduct credentials for marketplace-specific push.

GTA V only — extracts credential fields from OwnedProduct and its raw_data,
then formats them using the platform-aware credential spec from the pipeline.
"""
from __future__ import annotations

from apps.inventory.models import OwnedProduct
from payload_pipeline.core.contracts import CredentialBundle
from payload_pipeline.games.gtav.account.credentials import format_platform_credentials


def build_credential_bundle(product: OwnedProduct) -> CredentialBundle:
    """Build a CredentialBundle from OwnedProduct fields."""
    return CredentialBundle(
        login=product.login or "",
        password=product.password or "",
        email_login=product.email or "",
        email_password=product.email_password or "",
        email_login_link=product.email_login_link or "",
        security_email=product.security_email or "",
        security_email_password=product.security_email_password or "",
    )


def _get_platform(product: OwnedProduct) -> str:
    """Extract main_platform from OwnedProduct.raw_data."""
    raw = product.raw_data or {}
    return str(raw.get("main_platform", "")).strip()


def _get_credential_extras(product: OwnedProduct) -> dict:
    """Extract platform-specific credential extras from raw_data."""
    raw = product.raw_data or {}
    extras = {}
    for key in (
        "steam_id", "steam_pass", "rock_id", "rock_pass",
        "psn_id", "psn_pass", "xbox_id", "xbox_pass",
        "dob", "birthday",
        "security_email_login_link",
    ):
        val = str(raw.get(key, "")).strip()
        if val:
            extras[key] = val
    # Normalize birthday → dob (credential spec uses "dob")
    if "birthday" in extras and "dob" not in extras:
        extras["dob"] = extras.pop("birthday")
    # security_email_login_link from OwnedProduct field if not in raw
    if "security_email_login_link" not in extras and product.security_email_login_link:
        extras["security_email_login_link"] = product.security_email_login_link
    return extras


def format_credential_for_marketplace(
    product: OwnedProduct,
    marketplace: str,
) -> str:
    """Format OwnedProduct credentials using platform-aware spec.

    All marketplaces use the same platform-aware output.
    Backup codes are appended for Eldorado only.
    """
    platform = _get_platform(product)
    creds = build_credential_bundle(product)
    extras = _get_credential_extras(product)

    result = format_platform_credentials(platform, creds, extras)

    # Append backup codes for Eldorado
    if marketplace == "eldorado":
        raw = product.raw_data or {}
        backup_codes = raw.get("email_backup_codes", "")
        if backup_codes:
            result += f"\nBackup Codes:\n{backup_codes}"

    return result
