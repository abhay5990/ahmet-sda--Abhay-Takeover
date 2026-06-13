"""Format OwnedProduct credentials for marketplace-specific push.

Supports two modes:
1. Spec-driven: uses CredentialSpec fields/templates to render credentials.
2. Legacy GTA fallback: uses pipeline format_platform_credentials().

The spec-driven path is preferred when a CredentialSpec is resolved.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from apps.inventory.models import OwnedProduct
from payload_pipeline.core.contracts import CredentialBundle
from payload_pipeline.games.gtav.account.credentials import format_platform_credentials

if TYPE_CHECKING:
    from apps.posting.models import CredentialSpec, OfferPool

from .presets import ROLE_TO_OWNED_PRODUCT_FIELD

# Matches {placeholder} but not {{escaped}}
_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")

# Matches "Label: " with nothing after the colon (empty value lines)
_EMPTY_VALUE_LINE_RE = re.compile(r"^[^:]+:\s*$")


def _is_empty_value_line(line: str) -> bool:
    """Check if a line is a label with no value (e.g. 'Security Email: ')."""
    return bool(_EMPTY_VALUE_LINE_RE.match(line))


# ── Legacy helpers (kept for GTA fallback) ───────────────────────


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


def _legacy_format(product: OwnedProduct, marketplace: str) -> str:
    """Legacy GTA pipeline formatting with backup codes."""
    platform = _get_platform(product)
    creds = build_credential_bundle(product)
    extras = _get_credential_extras(product)

    result = format_platform_credentials(platform, creds, extras)

    if marketplace == "eldorado":
        raw = product.raw_data or {}
        backup_codes = raw.get("email_backup_codes", "")
        if backup_codes:
            result += f"\nBackup Codes:\n{backup_codes}"

    return result


# ── Spec-driven rendering ────────────────────────────────────────


def build_credential_render_context(
    product: OwnedProduct,
    spec: CredentialSpec,
) -> dict[str, str]:
    """Build a render context dict from product + spec.

    Maps OwnedProduct fixed columns and raw_data extras to spec field keys.
    This is the source of truth for spec-driven rendering.
    """
    from .spec_resolver import build_reverse_role_map

    reverse_map = build_reverse_role_map(spec)
    context: dict[str, str] = {}

    for field_key, role in reverse_map.items():
        owned_field = ROLE_TO_OWNED_PRODUCT_FIELD.get(role)
        if owned_field:
            context[field_key] = str(getattr(product, owned_field, "") or "")
        elif role == "extra":
            # Look in raw_data for extras
            raw = product.raw_data or {}
            val = str(raw.get(field_key, "")).strip()
            # Also check credential_values if stored by spec-driven ingestion
            cred_values = raw.get("credential_values") or {}
            if not val and isinstance(cred_values, dict):
                val = str(cred_values.get(field_key, "")).strip()
            context[field_key] = val

    # Add system keys
    raw = product.raw_data or {}
    backup_codes = raw.get("email_backup_codes", "")
    if backup_codes:
        context["email_backup_codes"] = str(backup_codes)

    return context


def render_template(
    template: str | dict,
    context: dict[str, str],
) -> str | dict:
    """Render a format template with a context dict.

    Supports both string templates and PA dict templates.
    Unknown placeholders render as empty strings.
    Literal {{ and }} are unescaped to { and }.
    """
    if isinstance(template, str):
        return _render_string(template, context)
    elif isinstance(template, dict):
        rendered = {}
        for key, value in template.items():
            if isinstance(value, str):
                rendered[key] = _render_string(value, context)
            else:
                rendered[key] = value
        return rendered
    return str(template)


def _render_string(template: str, context: dict[str, str]) -> str:
    """Render a string template, replacing {key} with context values.

    Lines where all placeholders resolved to empty are dropped
    (e.g. "Security Email: " becomes an empty-valued line and is removed).
    """
    def replacer(match):
        key = match.group(1)
        return context.get(key, "")

    result = _PLACEHOLDER_RE.sub(replacer, template)
    # Unescape literal braces
    result = result.replace("{{", "{").replace("}}", "}")
    # Drop lines where the value part is empty (e.g. "Label: ")
    lines = result.split("\n")
    filtered = [line for line in lines if not _is_empty_value_line(line)]
    return "\n".join(filtered)


def format_credential_by_spec(
    product: OwnedProduct,
    spec: CredentialSpec,
    marketplace: str,
) -> str | dict:
    """Format credentials using a specific CredentialSpec."""
    context = build_credential_render_context(product, spec)
    template = (spec.format_templates or {}).get(marketplace)

    if not template:
        # No template for this marketplace — build a plain text fallback
        lines = []
        for field in spec.fields:
            key = field.get("key", "") if isinstance(field, dict) else field.key
            label = field.get("label", key) if isinstance(field, dict) else field.label
            val = context.get(key, "")
            if val:
                lines.append(f"{label}: {val}")
        result = "\n".join(lines)
    else:
        result = render_template(template, context)

    # Eldorado backup codes guard: append only if template didn't already use placeholder
    if marketplace == "eldorado" and isinstance(result, str):
        raw = product.raw_data or {}
        backup_codes = raw.get("email_backup_codes", "")
        if backup_codes:
            template_str = template if isinstance(template, str) else ""
            if "{email_backup_codes}" not in template_str:
                result += f"\nBackup Codes:\n{backup_codes}"

    return result


# ── Public entry point ───────────────────────────────────────────


def format_credential_for_marketplace(
    product: OwnedProduct,
    marketplace: str,
    pool: OfferPool | None = None,
) -> str:
    """Format OwnedProduct credentials for a marketplace.

    Tries spec-driven rendering first (from pool or product's stored spec_id).
    Falls back to legacy GTA pipeline formatting.
    """
    spec = _resolve_product_spec(product, pool)

    if spec:
        result = format_credential_by_spec(product, spec, marketplace)
        # PA returns dict from format_credential_by_spec; for non-PA callers
        # that expect a string (Eldorado/Gameboost), join dict values
        if isinstance(result, dict):
            return result.get("instruction", "\n".join(str(v) for v in result.values()))
        return result

    return _legacy_format(product, marketplace)


def _resolve_product_spec(
    product: OwnedProduct,
    pool: OfferPool | None = None,
) -> CredentialSpec | None:
    """Try to find the CredentialSpec for a product/pool."""
    if pool:
        from .spec_resolver import resolve_spec
        return resolve_spec(pool)

    # Check if product was ingested with a spec
    raw = product.raw_data or {}
    spec_id = raw.get("credential_spec_id")
    if spec_id:
        from apps.posting.models import CredentialSpec
        try:
            spec = CredentialSpec.objects.get(id=spec_id, is_active=True)
            return spec
        except CredentialSpec.DoesNotExist:
            pass

    return None
