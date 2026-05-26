"""Unit tests for persisted Listing.variant slug helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from apps.posting.services.variant_slug import (
    resolve_listing_variant_slug,
    variant_value_contains_slug,
)


class Subject:
    region = 'EU'


def test_resolve_listing_variant_slug_builds_region_platform_composite() -> None:
    variant_ctx = {
        'region': {
            'EU': {'slug': 'eu'},
        },
        'platform': {
            'pc': {'slug': 'pc'},
            'psn': {'slug': 'psn'},
        },
    }

    assert resolve_listing_variant_slug(
        subject=Subject(),
        variant_ctx=variant_ctx,
        selected_variants={'platform': 'pc'},
    ) == 'eu-pc'


def test_variant_value_contains_slug_ignores_known_single_slug_prefixes() -> None:
    known_slugs = {'pc', 'pc-enhanced'}

    assert variant_value_contains_slug(
        'eu-pc',
        'pc',
        known_slugs=known_slugs,
    )
    assert not variant_value_contains_slug(
        'pc-enhanced',
        'pc',
        known_slugs=known_slugs,
    )
    assert not variant_value_contains_slug(
        'pc-enhanced-eu',
        'pc',
        known_slugs={*known_slugs, 'eu'},
    )
