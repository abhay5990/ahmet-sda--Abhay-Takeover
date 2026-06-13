"""Credential field schema, validators, and preset definitions.

CredentialFieldSchema defines the shape of each field in a CredentialSpec.
Validators ensure spec integrity at save time.
Presets provide code-level fallback specs for games without DB specs.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from django.core.exceptions import ValidationError
from pydantic import BaseModel


# ── Field Schema ─────────────────────────────────────────────────


VALID_ROLES = frozenset({
    "login",
    "password",
    "email",
    "email_password",
    "email_login_link",
    "security_email",
    "security_email_password",
    "security_email_login_link",
    "extra",
})

CANONICAL_MARKETPLACE_KEYS = frozenset({"eldorado", "gameboost", "playerauctions"})

# Roles that map to fixed OwnedProduct columns
ROLE_TO_OWNED_PRODUCT_FIELD: dict[str, str] = {
    "login": "login",
    "password": "password",
    "email": "email",
    "email_password": "email_password",
    "email_login_link": "email_login_link",
    "security_email": "security_email",
    "security_email_password": "security_email_password",
    "security_email_login_link": "security_email_login_link",
}


class CredentialFieldSchema(BaseModel):
    key: str
    label: str
    required: bool = True
    role: Literal[
        "login",
        "password",
        "email",
        "email_password",
        "email_login_link",
        "security_email",
        "security_email_password",
        "security_email_login_link",
        "extra",
    ] = "extra"


# ── Validators ───────────────────────────────────────────────────

# Matches {placeholder} but not {{escaped}}
_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")

# System keys allowed in templates beyond field keys
_SYSTEM_TEMPLATE_KEYS = frozenset({"email_backup_codes"})


def validate_credential_fields(fields: Any) -> list[CredentialFieldSchema]:
    """Validate and parse credential fields JSON.

    Raises django.core.exceptions.ValidationError on invalid input.
    Returns parsed list of CredentialFieldSchema.
    """
    if not isinstance(fields, list):
        raise ValidationError({"fields": "fields must be a list"})

    if not fields:
        raise ValidationError({"fields": "fields cannot be empty"})

    parsed: list[CredentialFieldSchema] = []
    seen_keys: set[str] = set()
    seen_roles: dict[str, int] = {}

    for i, item in enumerate(fields):
        if not isinstance(item, dict):
            raise ValidationError({"fields": f"fields[{i}] must be a dict"})
        try:
            schema = CredentialFieldSchema(**item)
        except Exception as exc:
            raise ValidationError({"fields": f"fields[{i}]: {exc}"}) from exc

        if schema.key in seen_keys:
            raise ValidationError(
                {"fields": f"Duplicate key '{schema.key}' in fields[{i}]"}
            )
        seen_keys.add(schema.key)

        if schema.role not in VALID_ROLES:
            raise ValidationError(
                {"fields": f"Unknown role '{schema.role}' in fields[{i}]"}
            )

        if schema.role != "extra":
            seen_roles.setdefault(schema.role, 0)
            seen_roles[schema.role] += 1

        parsed.append(schema)

    # Exactly one login and one password role required
    if seen_roles.get("login", 0) != 1:
        raise ValidationError(
            {"fields": "Exactly one field with role='login' is required"}
        )
    if seen_roles.get("password", 0) != 1:
        raise ValidationError(
            {"fields": "Exactly one field with role='password' is required"}
        )

    # Non-extra roles must appear at most once
    for role, count in seen_roles.items():
        if role not in ("login", "password", "extra") and count > 1:
            raise ValidationError(
                {"fields": f"Role '{role}' appears {count} times, expected at most 1"}
            )

    return parsed


def validate_format_templates(
    format_templates: Any,
    fields: Any,
) -> None:
    """Validate format_templates against field keys.

    Raises ValidationError if templates reference unknown placeholders
    or use non-canonical marketplace keys.
    """
    if not format_templates:
        return

    if not isinstance(format_templates, dict):
        raise ValidationError(
            {"format_templates": "format_templates must be a dict"}
        )

    # Build allowed placeholder keys
    if isinstance(fields, list):
        try:
            parsed = [
                CredentialFieldSchema(**f) if isinstance(f, dict) else f
                for f in fields
            ]
            allowed_keys = {f.key if isinstance(f, CredentialFieldSchema) else f.get("key", "") for f in parsed}
        except Exception:
            allowed_keys = {f.get("key", "") if isinstance(f, dict) else "" for f in fields}
    else:
        allowed_keys = set()

    allowed_keys |= _SYSTEM_TEMPLATE_KEYS

    for marketplace, template in format_templates.items():
        if marketplace not in CANONICAL_MARKETPLACE_KEYS:
            raise ValidationError(
                {"format_templates": f"Unknown marketplace key '{marketplace}'. Use: {', '.join(sorted(CANONICAL_MARKETPLACE_KEYS))}"}
            )
        _validate_template_placeholders(template, allowed_keys, marketplace)


def _validate_template_placeholders(
    template: str | dict,
    allowed_keys: set[str],
    marketplace: str,
) -> None:
    """Check that all {placeholders} in a template are in allowed_keys."""
    if isinstance(template, str):
        _check_placeholders(template, allowed_keys, marketplace)
    elif isinstance(template, dict):
        for key, value in template.items():
            if isinstance(value, str):
                _check_placeholders(value, allowed_keys, f"{marketplace}.{key}")
    else:
        raise ValidationError(
            {"format_templates": f"Template for '{marketplace}' must be a string or dict"}
        )


def _check_placeholders(text: str, allowed_keys: set[str], context: str) -> None:
    for match in _PLACEHOLDER_RE.finditer(text):
        placeholder = match.group(1)
        if placeholder not in allowed_keys:
            raise ValidationError(
                {"format_templates": f"Unknown placeholder '{{{placeholder}}}' in {context}. Allowed: {', '.join(sorted(allowed_keys))}"}
            )


# ── Preset Definitions ───────────────────────────────────────────


def _generic_fields() -> list[dict]:
    return [
        {"key": "login", "label": "Login", "required": True, "role": "login"},
        {"key": "password", "label": "Password", "required": True, "role": "password"},
        {"key": "email", "label": "Email", "required": False, "role": "email"},
        {"key": "email_password", "label": "Email Password", "required": False, "role": "email_password"},
    ]


def _generic_format_templates() -> dict:
    text = "Login: {login}\nPassword: {password}\nEmail: {email}\nEmail Password: {email_password}"
    return {
        "eldorado": text,
        "gameboost": text,
        "playerauctions": {
            "loginName": "{login}",
            "password": "{password}",
            "instruction": text,
            "ownerEmail": "{email}",
        },
    }


def _gta_ps_fields() -> list[dict]:
    return [
        {"key": "psn_id", "label": "PSN ID", "required": True, "role": "login"},
        {"key": "psn_pass", "label": "PSN Password", "required": True, "role": "password"},
        {"key": "email", "label": "Email", "required": False, "role": "email"},
        {"key": "email_password", "label": "Email Password", "required": False, "role": "email_password"},
        {"key": "security_email", "label": "Security Email", "required": False, "role": "security_email"},
        {"key": "security_email_password", "label": "Security Email Password", "required": False, "role": "security_email_password"},
        {"key": "dob", "label": "Date of Birth", "required": False, "role": "extra"},
    ]


def _gta_ps_format_templates() -> dict:
    text = "PSN ID: {psn_id}\nPSN Pass: {psn_pass}\nEmail: {email}\nEmail Pass: {email_password}\nSecurity Email: {security_email}\nSecurity Email Pass: {security_email_password}\nDoB: {dob}"
    return {
        "eldorado": text,
        "gameboost": text,
        "playerauctions": {
            "loginName": "{psn_id}",
            "password": "{psn_pass}",
            "instruction": text,
            "ownerEmail": "{email}",
        },
    }


def _gta_xbox_fields() -> list[dict]:
    return [
        {"key": "xbox_id", "label": "Xbox ID", "required": True, "role": "login"},
        {"key": "xbox_pass", "label": "Xbox Password", "required": True, "role": "password"},
        {"key": "email", "label": "Email", "required": False, "role": "email"},
        {"key": "email_password", "label": "Email Password", "required": False, "role": "email_password"},
    ]


def _gta_xbox_format_templates() -> dict:
    text = "Xbox ID: {xbox_id}\nXbox Pass: {xbox_pass}\nEmail: {email}\nEmail Pass: {email_password}"
    return {
        "eldorado": text,
        "gameboost": text,
        "playerauctions": {
            "loginName": "{xbox_id}",
            "password": "{xbox_pass}",
            "instruction": text,
            "ownerEmail": "{email}",
        },
    }


def _gta_pc_fields() -> list[dict]:
    return [
        {"key": "steam_id", "label": "Steam ID", "required": True, "role": "login"},
        {"key": "steam_pass", "label": "Steam Password", "required": True, "role": "password"},
        {"key": "rock_id", "label": "Rockstar ID", "required": False, "role": "extra"},
        {"key": "rock_pass", "label": "Rockstar Password", "required": False, "role": "extra"},
        {"key": "email", "label": "Email", "required": False, "role": "email"},
        {"key": "email_password", "label": "Email Password", "required": False, "role": "email_password"},
    ]


def _gta_pc_format_templates() -> dict:
    text = "Steam ID: {steam_id}\nSteam Pass: {steam_pass}\nRockstar ID: {rock_id}\nRockstar Pass: {rock_pass}\nEmail: {email}\nEmail Pass: {email_password}"
    return {
        "eldorado": text,
        "gameboost": text,
        "playerauctions": {
            "loginName": "{steam_id}",
            "password": "{steam_pass}",
            "instruction": text,
            "ownerEmail": "{email}",
        },
    }


# Master preset registry: slug -> (name, fields, format_templates)
# Keys follow the pattern: game_slug or game_slug:variant_slug
CREDENTIAL_PRESETS: dict[str, tuple[str, list[dict], dict]] = {
    # Generic default
    "_default": ("Generic", _generic_fields(), _generic_format_templates()),
    # Fortnite (single variant, same as generic)
    "fortnite": ("Fortnite", _generic_fields(), _generic_format_templates()),
    # Valorant
    "valorant": ("Valorant", _generic_fields(), _generic_format_templates()),
    # CS2
    "cs2": ("CS2", _generic_fields(), _generic_format_templates()),
    # GTA V variants
    "grand-theft-auto-5:ps4": ("GTA V - PS4", _gta_ps_fields(), _gta_ps_format_templates()),
    "grand-theft-auto-5:ps5": ("GTA V - PS5", _gta_ps_fields(), _gta_ps_format_templates()),
    "grand-theft-auto-5:xbox-one": ("GTA V - Xbox One", _gta_xbox_fields(), _gta_xbox_format_templates()),
    "grand-theft-auto-5:xbox-series": ("GTA V - Xbox Series", _gta_xbox_fields(), _gta_xbox_format_templates()),
    "grand-theft-auto-5:pc-legacy": ("GTA V - PC Legacy", _gta_pc_fields(), _gta_pc_format_templates()),
    "grand-theft-auto-5:pc-enhanced": ("GTA V - PC Enhanced", _gta_pc_fields(), _gta_pc_format_templates()),
    # Forza Horizon 5
    "forza-horizon-5": ("Forza Horizon 5", _generic_fields(), _generic_format_templates()),
    # Forza Motorsport
    "forza-motorsport": ("Forza Motorsport", _generic_fields(), _generic_format_templates()),
    # Rust
    "rust": ("Rust", _generic_fields(), _generic_format_templates()),
    # New World
    "new-world": ("New World", _generic_fields(), _generic_format_templates()),
    # Steam generic
    "steam-generic": ("Steam Generic", _generic_fields(), _generic_format_templates()),
    # Xbox generic
    "xbox-generic": ("Xbox Generic", _generic_fields(), _generic_format_templates()),
    # PSN generic
    "psn-generic": ("PSN Generic", _generic_fields(), _generic_format_templates()),
}


def get_preset(game_slug: str, variant_slug: str | None = None) -> tuple[str, list[dict], dict] | None:
    """Look up a code-level preset by game slug and optional variant slug.

    Returns (name, fields, format_templates) or None if no preset.
    """
    if variant_slug:
        key = f"{game_slug}:{variant_slug}"
        if key in CREDENTIAL_PRESETS:
            return CREDENTIAL_PRESETS[key]

    if game_slug in CREDENTIAL_PRESETS:
        return CREDENTIAL_PRESETS[game_slug]

    return CREDENTIAL_PRESETS.get("_default")
