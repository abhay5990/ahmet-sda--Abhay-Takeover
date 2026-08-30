"""Unit tests for non-SAB dropship cleanup helpers.

Usage:
    cd backend && python -m pytest ../tests/unit/test_non_sab_cleanup.py -v
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'payload_pipeline'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'apis_sdk'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

import django
django.setup()

from apps.posting.services.dropship.non_sab_cleanup import extract_eldorado_game_id
from apps.posting.services.dropship.sources.eldorado import SAB_GAME_ID


class TestExtractEldoradoGameId:
    def test_top_level_int(self):
        assert extract_eldorado_game_id({'gameId': SAB_GAME_ID}) == SAB_GAME_ID

    def test_top_level_string(self):
        assert extract_eldorado_game_id({'gameId': '430'}) == 430

    def test_nested_offer(self):
        assert extract_eldorado_game_id({'offer': {'gameId': 259}}) == 259

    def test_missing(self):
        assert extract_eldorado_game_id({}) is None
        assert extract_eldorado_game_id(None) is None
