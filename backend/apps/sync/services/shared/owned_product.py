"""Shared OwnedProduct get-or-create helper for all sync services.

Central upsert point for OwnedProduct — ALL sources (LZT, Eldorado,
Gameboost, PlayerAuctions) use this single function.

Identity: (category, login) — one record per real-world account.
Password policy: first writer wins, subsequent sources do NOT overwrite.

Usage:
    from apps.sync.services.shared.owned_product import get_or_create_owned_product

    owned = get_or_create_owned_product(
        parsed=parsed_creds,
        category=game.category,
        game=game,
        source_account=raw_payload.integration_account,
        status=OwnedProductStatus.SOLD,
        price=order_price / 2,
        currency='USD',
        purchased_at=sold_at,
        raw_data=payload,
    )
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.inventory.models import OwnedProduct
from apps.inventory.ref_key import generate_ref_key
from apps.sync.services.shared.credentials import ParsedCredentials

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount
    from apps.inventory.models import Category, DropshipProduct, Game

logger = logging.getLogger(__name__)

# Category names where password is not required (e.g. Supercell ID login).
# For these, a default password "1" is used when none is parsed.
_NO_PASSWORD_CATEGORIES = {'supercell'}

# Minimum password length for categories that require passwords.
_MIN_PASSWORD_LENGTH = 4

# ── In-memory cache for bulk operations ────────────────────────────────
# Key: (category_id, login) → OwnedProduct instance
_owned_cache: dict[tuple[int, str], OwnedProduct] = {}


def warm_owned_product_cache() -> int:
    """Pre-load all OwnedProducts into memory cache. Returns count."""
    _owned_cache.clear()
    qs = OwnedProduct.objects.select_related('category', 'game')
    count = 0
    for op in qs.iterator():
        _owned_cache[(op.category_id, op.login)] = op
        count += 1
    return count


def clear_owned_product_cache() -> None:
    _owned_cache.clear()


def _resolve_password(
    parsed: ParsedCredentials,
    category: 'Category',
) -> str:
    """Determine the effective password for OwnedProduct creation.

    - Supercell category: default "1" if no password parsed.
    - Others: use parsed.password, fall back to parsed.email_password
      (for formats where login == email and only email_password exists).
    - Returns empty string if no valid password can be determined.
    """
    category_name = (category.name or '').lower() if category else ''

    password = parsed.password

    # Fallback: use email_password when login == email (same account)
    if not password and parsed.email_password and parsed.login == parsed.email:
        password = parsed.email_password

    # Supercell: default to "1" if still no password
    if not password and category_name in _NO_PASSWORD_CATEGORIES:
        return '1'

    if not password:
        return ''

    # Reject garbage passwords (too short) — still create record but without password
    if category_name not in _NO_PASSWORD_CATEGORIES:
        if len(password) < _MIN_PASSWORD_LENGTH:
            return ''

    return password


def get_or_create_owned_product(
    parsed: ParsedCredentials,
    category: 'Category',
    game: 'Game | None',
    source_account: 'IntegrationAccount | None',
    status: str,
    price: Decimal | None = None,
    currency: str = 'USD',
    purchased_at: datetime | None = None,
    raw_data: dict | None = None,
    product_origin: 'DropshipProduct | None' = None,
    source_product_id: int | None = None,
) -> OwnedProduct | None:
    """Match existing or create new OwnedProduct from parsed credentials.

    Lookup: (category, login) — canonical identity.
    Password: first writer wins, never overwritten by subsequent sources.
    Empty fields: filled from new parse data (don't overwrite existing).

    Returns None only when login is missing.
    """
    if not parsed.login:
        logger.debug("Skipping OwnedProduct creation: login missing")
        return None

    password = _resolve_password(parsed, category)
    login = parsed.login.strip()
    password_hash = hashlib.sha256(password.encode()).hexdigest() if password else ''

    # Check in-memory cache first (populated by warm_owned_product_cache)
    cache_key = (category.pk, login)
    existing = _owned_cache.get(cache_key)

    if existing is None:
        # DB lookup
        existing = (
            OwnedProduct.objects
            .filter(category=category, login=login)
            .first()
        )
        if existing:
            _owned_cache[cache_key] = existing

    if existing:
        # Password: first writer wins. Fill if currently empty.
        updated_fields = []
        if password and not existing.password:
            existing.password = password
            existing.password_hash = password_hash
            updated_fields.extend(['password', 'password_hash'])
        elif password and existing.password_hash and existing.password_hash != password_hash:
            logger.info(
                "OwnedProduct #%s (%s / %s): password mismatch from new source, "
                "keeping existing password",
                existing.pk, category, parsed.login,
            )

        # Fill in empty fields from new parse (don't overwrite existing data)
        field_updates = {
            'email': parsed.email,
            'email_password': parsed.email_password,
            'email_login_link': parsed.email_login_link,
            'security_email': parsed.security_email,
            'security_email_password': parsed.security_email_password,
        }
        for field_name, new_value in field_updates.items():
            if new_value and not getattr(existing, field_name):
                setattr(existing, field_name, new_value)
                updated_fields.append(field_name)

        if not existing.game and game:
            existing.game = game
            updated_fields.append('game')

        if raw_data and not existing.raw_data:
            existing.raw_data = raw_data
            updated_fields.append('raw_data')

        if source_product_id and not existing.source_product_id:
            existing.source_product_id = source_product_id
            updated_fields.append('source_product_id')

        if not existing.ref_key:
            existing.ref_key = generate_ref_key(source_product_id or existing.source_product_id)
            updated_fields.append('ref_key')

        if updated_fields:
            existing.save(update_fields=updated_fields + ['updated_at'])
            logger.info(
                "Updated OwnedProduct #%s (%s / %s) empty fields: %s",
                existing.pk, category, parsed.login, ', '.join(updated_fields),
            )

        return existing

    # No existing record — create new
    ref_key = generate_ref_key(source_product_id)

    obj = OwnedProduct.objects.create(
        category=category,
        login=login,
        password_hash=password_hash,
        password=password,
        email=parsed.email,
        email_password=parsed.email_password,
        email_login_link=parsed.email_login_link,
        security_email=parsed.security_email,
        security_email_password=parsed.security_email_password,
        game=game,
        status=status,
        source_account=source_account,
        source_product_id=source_product_id,
        price=price,
        currency=currency,
        purchased_at=purchased_at,
        raw_data=raw_data or {},
        product_origin=product_origin,
        ref_key=ref_key,
    )

    # Update cache
    _owned_cache[cache_key] = obj

    logger.info(
        "Created OwnedProduct #%s (%s / %s) from %s",
        obj.pk, category, parsed.login, status,
    )

    return obj
