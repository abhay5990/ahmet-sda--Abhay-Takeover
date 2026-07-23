"""Focused regression tests for fixed platform routing."""

from apps.posting.services.variant_routing import VariantRouter


def test_select_fixed_matches_raw_enhanced_slug_to_human_source_key():
    context = {
        "platform": {
            "PC - Legacy": {"slug": "pc-legacy"},
            "PC - Enhanced": {"slug": "pc-enhanced"},
        },
    }

    assert VariantRouter(context).select_fixed("platform", "pc-enhanced") == "pc-enhanced"
