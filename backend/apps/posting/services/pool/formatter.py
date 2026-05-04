"""Format OwnedProduct credentials for marketplace-specific push.

GTA V only — extracts credential fields from OwnedProduct and its raw_data,
then formats them into the string format each marketplace expects.
"""
from __future__ import annotations

from typing import Any

from apps.inventory.models import OwnedProduct


def format_eldorado_credential(product: OwnedProduct) -> str:
    """Build Eldorado accountSecretDetails entry from OwnedProduct.

    Returns a multiline string matching the GTA V Eldorado delivery format:
        Login: ...
        Password: ...
        Email: ...
        ...
    """
    raw = product.raw_data or {}
    lines: list[str] = []

    if product.login:
        lines.append(f"Login: {product.login}")
    if product.password:
        lines.append(f"Password: {product.password}")
    if product.email:
        lines.append(f"Email: {product.email}")
    if product.email_password:
        lines.append(f"Email Password: {product.email_password}")
    if product.email_login_link:
        lines.append(f"Email Login Link: {product.email_login_link}")
    if product.security_email:
        lines.append(f"Security Email: {product.security_email}")
    if product.security_email_password:
        lines.append(f"Security Email Password: {product.security_email_password}")
    if product.security_email_login_link:
        lines.append(f"Security Email Login Link: {product.security_email_login_link}")

    birthday = raw.get('birthday', '')
    if birthday:
        lines.append(f"Birthday: {birthday}")

    backup_codes = raw.get('email_backup_codes', '')
    if backup_codes:
        lines.append(f"Backup Codes:\n{backup_codes}")

    return "\n".join(lines)


def format_gameboost_credential(product: OwnedProduct) -> str:
    """Build Gameboost credential string from OwnedProduct.

    Gameboost add_offer_credentials expects a list of formatted strings.
    Each string contains login:password and optional email fields.
    """
    parts: list[str] = []

    if product.login:
        parts.append(f"Login: {product.login}")
    if product.password:
        parts.append(f"Password: {product.password}")
    if product.email:
        parts.append(f"Email: {product.email}")
    if product.email_password:
        parts.append(f"Email Password: {product.email_password}")
    if product.email_login_link:
        parts.append(f"Email Login Link: {product.email_login_link}")
    if product.security_email:
        parts.append(f"Security Email: {product.security_email}")
    if product.security_email_password:
        parts.append(f"Security Email Password: {product.security_email_password}")

    return "\n".join(parts)


def format_credential_for_marketplace(
    product: OwnedProduct,
    marketplace: str,
) -> str:
    """Dispatch to the correct formatter based on marketplace provider."""
    formatters: dict[str, Any] = {
        'eldorado': format_eldorado_credential,
        'gameboost': format_gameboost_credential,
    }
    formatter = formatters.get(marketplace)
    if not formatter:
        raise ValueError(f"No credential formatter for marketplace: {marketplace}")
    return formatter(product)
