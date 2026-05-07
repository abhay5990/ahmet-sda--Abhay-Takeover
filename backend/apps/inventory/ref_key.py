"""Ref key generation for OwnedProduct traceability.

Format: #ABC1234 — 3 uppercase letters + 4 digits.
Generated deterministically from source_product_id (LZT item_id) when available,
or randomly when no item_id exists.

Collision handling: retry with random fallback if the generated key already exists.
"""

from __future__ import annotations

import random
import string

from apps.inventory.models import OwnedProduct


def generate_ref_key(source_product_id: int | None = None) -> str:
    """Generate a unique ref key in #ABC1234 format.

    If source_product_id is provided, generates deterministically first.
    Falls back to random generation if collision detected.
    """
    if source_product_id:
        candidate = _deterministic_key(source_product_id)
        if not OwnedProduct.objects.filter(ref_key=candidate).exists():
            return candidate

    # Random generation with collision check
    for _ in range(20):
        candidate = _random_key()
        if not OwnedProduct.objects.filter(ref_key=candidate).exists():
            return candidate

    raise RuntimeError("Failed to generate unique ref_key after 20 attempts")


def _deterministic_key(item_id: int) -> str:
    """Derive a key from item_id using simple hash-based mapping."""
    h = hash(item_id) & 0xFFFFFFFF
    letters = ''
    val = h
    for _ in range(3):
        letters += string.ascii_uppercase[val % 26]
        val //= 26
    digits = f'{h % 10000:04d}'
    return f'#{letters}{digits}'


def _random_key() -> str:
    letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    digits = ''.join(random.choices(string.digits, k=4))
    return f'#{letters}{digits}'
