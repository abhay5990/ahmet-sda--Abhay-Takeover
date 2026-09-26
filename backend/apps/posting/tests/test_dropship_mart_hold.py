import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.posting.services.dropship.scheduler import DropshipScheduler


class DropshipMartHoldTests(SimpleTestCase):
    @patch.dict(os.environ, {'PA_MART_CREATE_HOLD': 'true'}, clear=False)
    def test_mart_config_is_held_before_poster_thread_start(self):
        config = SimpleNamespace(
            store=SimpleNamespace(
                provider='playerauctions',
                slug='playerauctions-csgosmurfkings',
            )
        )

        self.assertTrue(DropshipScheduler._mart_poster_is_held(config))

    @patch.dict(os.environ, {'PA_MART_CREATE_HOLD': 'true'}, clear=False)
    def test_other_pa_store_is_not_held(self):
        config = SimpleNamespace(
            store=SimpleNamespace(
                provider='playerauctions',
                slug='playerauctions-vapenation234',
            )
        )

        self.assertFalse(DropshipScheduler._mart_poster_is_held(config))

    @patch.dict(os.environ, {'PA_MART_CREATE_HOLD': 'false'}, clear=False)
    def test_mart_config_can_only_run_after_explicit_hold_lift(self):
        config = SimpleNamespace(
            store=SimpleNamespace(
                provider='playerauctions',
                slug='playerauctions-csgosmurfkings',
            )
        )

        self.assertFalse(DropshipScheduler._mart_poster_is_held(config))
