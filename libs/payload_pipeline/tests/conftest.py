"""Shared fixtures and helpers for payload_pipeline tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make test helper modules importable (e.g. _variant_ctx)
sys.path.insert(0, str(Path(__file__).resolve().parent / "unit"))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Load a JSON fixture from the fixtures directory."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def load_fixture():
    """Pytest fixture that returns a callable to load JSON fixtures by name."""
    return _load_fixture
