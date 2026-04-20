"""Shared credential resolution helpers for resolver implementations."""

from __future__ import annotations

from ..core.contracts import CredentialBundle
from ..core.exceptions import SourceValidationError


def resolve_credentials(
    *sources: object,
    kind: str = "stock",
    game_name: str = "",
) -> CredentialBundle:
    """Return credentials from the first source that has them.

    In dropshipping mode, returns an empty ``CredentialBundle``.
    In stock mode, iterates over *sources* (each must have a ``.credentials``
    attribute) and returns the first non-empty bundle.

    Raises ``SourceValidationError`` if stock mode but no source has credentials.
    """
    if kind != "stock":
        return CredentialBundle()

    for source in sources:
        if source is None:
            continue
        creds = getattr(source, "credentials", None)
        if isinstance(creds, CredentialBundle) and not creds.is_empty:
            return creds

    label = f"{game_name} " if game_name else ""
    source_names = ", ".join(
        repr(type(s).__name__) for s in sources if s is not None
    )
    raise SourceValidationError(
        f"{label}stock mode requires credentials from sources ({source_names})."
    )
