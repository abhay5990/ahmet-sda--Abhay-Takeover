"""Resolved model validation for payload_pipeline.

Provides a lightweight ``validate_resolved`` function that checks critical
fields shared by all resolved account models.  Game-specific validation
can be added via ``__post_init__`` in individual model dataclasses.

This is intentionally minimal — we validate only fields that, if invalid,
would produce silently broken marketplace payloads.
"""

from __future__ import annotations

import logging

from .contracts import ResolvedAccountBase
from .enums import ListingKind
from .exceptions import SourceValidationError


logger = logging.getLogger(__name__)


def validate_resolved(
    subject: ResolvedAccountBase,
    *,
    game: str = "",
    kind: ListingKind | str = ListingKind.STOCK,
) -> None:
    """Validate critical fields on a resolved account model.

    Raises ``SourceValidationError`` for hard failures that would produce
    broken payloads.  Logs warnings for soft issues.

    Checks:
    1. ``item_id`` must not be empty.
    2. ``price`` must be non-negative.
    3. In stock mode, ``credentials`` must not be empty.
    """
    prefix = f"[{game}] " if game else ""

    if not isinstance(subject, ResolvedAccountBase):
        raise SourceValidationError(
            f"{prefix}Resolved model must be a ResolvedAccountBase subclass, "
            f"got {type(subject).__name__}"
        )

    # 1. item_id — must be non-empty
    if not subject.item_id:
        raise SourceValidationError(
            f"{prefix}Resolved model has empty item_id"
        )

    # 2. price — must be non-negative
    if subject.price < 0:
        raise SourceValidationError(
            f"{prefix}Resolved model has negative price: {subject.price}"
        )
    if subject.price == 0:
        logger.warning("%sResolved model has zero price", prefix)

    # 3. credentials in stock kind — must not be empty
    if kind == ListingKind.STOCK and subject.credentials.is_empty:
        logger.warning(
            "%sStock mode but credentials are empty — "
            "marketplace payloads may be incomplete",
            prefix,
        )
