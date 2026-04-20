"""Unit tests for scheduler DB models — 3-concept worker state model.

Tests DropshippingJobConfig (poster), CleanerConfig, SchedulerHeartbeat.

Usage:
    cd backend && python -m pytest ../tests/unit/test_scheduler_models.py -v
"""

import sys
import os
from datetime import timedelta

import django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()

import pytest
from django.utils import timezone
from django.db import IntegrityError

from apps.posting.models import (
    CleanerConfig,
    DropshippingJobConfig,
    SchedulerHeartbeat,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def integration_account(db):
    """Minimal IntegrationAccount for FK satisfaction."""
    from apps.integrations.models import IntegrationAccount
    return IntegrationAccount.objects.create(
        name='Test Account',
        provider='lzt',
        slug='test-lzt-account',
    )


@pytest.fixture
def target_account(db):
    from apps.integrations.models import IntegrationAccount
    return IntegrationAccount.objects.create(
        name='Target Store',
        provider='gameboost',
        slug='test-gameboost-store',
    )


@pytest.fixture
def game(db):
    from apps.inventory.models import Game
    return Game.objects.create(name='Fortnite', slug='fortnite')


@pytest.fixture
def config(db, integration_account, target_account, game):
    return DropshippingJobConfig.objects.create(
        source_account=integration_account,
        store=target_account,
        game=game,
    )


@pytest.fixture
def cleaner_config(db, integration_account):
    return CleanerConfig.objects.create(
        source_account=integration_account,
    )


@pytest.fixture
def heartbeat(db):
    return SchedulerHeartbeat.objects.create(
        service_name='dropship',
        last_seen=timezone.now(),
    )


# ---------------------------------------------------------------------------
# DropshippingJobConfig — 3-concept poster state
# ---------------------------------------------------------------------------

class TestDropshippingJobConfigDefaults:
    """New config has correct defaults (3-concept model)."""

    def test_enabled_default(self, config):
        """INTENT default: enabled=True."""
        assert config.enabled is True

    def test_disabled_reason_default(self, config):
        """CONDITION default: empty string."""
        assert config.disabled_reason == ''

    def test_poster_running_default(self, config):
        """ACTUAL default: not running."""
        assert config.poster_running is False

    def test_poster_cycle_interval_default(self, config):
        assert config.poster_cycle_interval == 300

    def test_poster_last_cycle_at_default(self, config):
        assert config.poster_last_cycle_at is None


class TestDropshippingJobConfigOperations:
    """Poster 3-concept state transitions."""

    def test_start_poster(self, config):
        """Scheduler starts poster: running=True."""
        config.poster_running = True
        config.save(update_fields=['poster_running'])
        config.refresh_from_db()
        assert config.poster_running is True

    def test_user_disable(self, config):
        """User disables config: enabled=False, disabled_reason empty."""
        config.enabled = False
        config.save(update_fields=['enabled'])
        config.refresh_from_db()
        assert config.enabled is False
        assert config.disabled_reason == ''

    def test_system_disable_with_reason(self, config):
        """System disables on error: enabled=False, disabled_reason set."""
        config.enabled = False
        config.disabled_reason = '5x consecutive rate limit (429)'
        config.poster_running = False
        config.save(update_fields=['enabled', 'disabled_reason', 'poster_running'])
        config.refresh_from_db()
        assert config.enabled is False
        assert config.disabled_reason == '5x consecutive rate limit (429)'
        assert config.poster_running is False

    def test_user_re_enable_clears_reason(self, config):
        """User re-enables: enabled=True, disabled_reason cleared."""
        config.enabled = False
        config.disabled_reason = 'rate limit'
        config.save(update_fields=['enabled', 'disabled_reason'])

        config.enabled = True
        config.disabled_reason = ''
        config.save(update_fields=['enabled', 'disabled_reason'])
        config.refresh_from_db()
        assert config.enabled is True
        assert config.disabled_reason == ''

    def test_graceful_stop(self, config):
        """Normal exit: running=False, enabled stays True."""
        config.poster_running = True
        config.save(update_fields=['poster_running'])

        config.poster_running = False
        config.save(update_fields=['poster_running'])
        config.refresh_from_db()
        assert config.poster_running is False
        assert config.enabled is True

    def test_cycle_interval_update(self, config):
        config.poster_cycle_interval = 600
        config.save(update_fields=['poster_cycle_interval'])
        config.refresh_from_db()
        assert config.poster_cycle_interval == 600

    def test_last_cycle_at_update(self, config):
        now = timezone.now()
        config.poster_last_cycle_at = now
        config.save(update_fields=['poster_last_cycle_at'])
        config.refresh_from_db()
        assert abs((config.poster_last_cycle_at - now).total_seconds()) < 1


class TestDropshippingJobConfigConstraints:
    """Existing constraints still work."""

    def test_unique_together(self, config, integration_account, target_account, game):
        with pytest.raises(IntegrityError):
            DropshippingJobConfig.objects.create(
                source_account=integration_account,
                store=target_account,
                game=game,
            )

    def test_str(self, config):
        s = str(config)
        assert '→' in s


# ---------------------------------------------------------------------------
# CleanerConfig — 3-concept cleaner state
# ---------------------------------------------------------------------------

class TestCleanerConfigDefaults:
    """New CleanerConfig has correct defaults."""

    def test_enabled_default(self, cleaner_config):
        assert cleaner_config.enabled is True

    def test_disabled_reason_default(self, cleaner_config):
        assert cleaner_config.disabled_reason == ''

    def test_running_default(self, cleaner_config):
        assert cleaner_config.running is False

    def test_cycle_interval_default(self, cleaner_config):
        assert cleaner_config.cycle_interval == 600

    def test_last_cycle_at_default(self, cleaner_config):
        assert cleaner_config.last_cycle_at is None


class TestCleanerConfigOperations:
    """Cleaner 3-concept state transitions."""

    def test_start_cleaner(self, cleaner_config):
        cleaner_config.running = True
        cleaner_config.save(update_fields=['running'])
        cleaner_config.refresh_from_db()
        assert cleaner_config.running is True

    def test_system_disable(self, cleaner_config):
        cleaner_config.enabled = False
        cleaner_config.disabled_reason = '3x consecutive server errors (5xx)'
        cleaner_config.running = False
        cleaner_config.save(update_fields=['enabled', 'disabled_reason', 'running'])
        cleaner_config.refresh_from_db()
        assert cleaner_config.enabled is False
        assert '5xx' in cleaner_config.disabled_reason

    def test_user_toggle(self, cleaner_config):
        cleaner_config.enabled = False
        cleaner_config.save(update_fields=['enabled'])
        cleaner_config.refresh_from_db()
        assert cleaner_config.enabled is False

        cleaner_config.enabled = True
        cleaner_config.disabled_reason = ''
        cleaner_config.save(update_fields=['enabled', 'disabled_reason'])
        cleaner_config.refresh_from_db()
        assert cleaner_config.enabled is True

    def test_cycle_interval_update(self, cleaner_config):
        cleaner_config.cycle_interval = 900
        cleaner_config.save(update_fields=['cycle_interval'])
        cleaner_config.refresh_from_db()
        assert cleaner_config.cycle_interval == 900

    def test_last_cycle_at(self, cleaner_config):
        now = timezone.now()
        cleaner_config.last_cycle_at = now
        cleaner_config.save(update_fields=['last_cycle_at'])
        cleaner_config.refresh_from_db()
        assert abs((cleaner_config.last_cycle_at - now).total_seconds()) < 1

    def test_one_to_one_constraint(self, cleaner_config, integration_account):
        """Only one CleanerConfig per source account."""
        with pytest.raises(IntegrityError):
            CleanerConfig.objects.create(source_account=integration_account)

    def test_str(self, cleaner_config):
        s = str(cleaner_config)
        assert 'Cleaner' in s


# ---------------------------------------------------------------------------
# SchedulerHeartbeat — pure process liveness
# ---------------------------------------------------------------------------

class TestSchedulerHeartbeatCreation:
    """SchedulerHeartbeat is pure heartbeat — no worker state."""

    def test_create_minimal(self, heartbeat):
        assert heartbeat.pk is not None
        assert heartbeat.service_name == 'dropship'

    def test_pid_default_null(self, heartbeat):
        assert heartbeat.pid is None

    def test_started_at_default_null(self, heartbeat):
        assert heartbeat.started_at is None

    def test_unique_service_name(self, heartbeat):
        with pytest.raises(IntegrityError):
            SchedulerHeartbeat.objects.create(
                service_name='dropship',
                last_seen=timezone.now(),
            )

    def test_str(self, heartbeat):
        s = str(heartbeat)
        assert 'dropship' in s

    def test_no_cleaner_fields(self, heartbeat):
        """Heartbeat should not have any cleaner fields (moved to CleanerConfig)."""
        assert not hasattr(heartbeat, 'cleaner_enabled')
        assert not hasattr(heartbeat, 'cleaner_status')
        assert not hasattr(heartbeat, 'cleaner_stop_requested')


class TestSchedulerHeartbeatOperations:
    """Heartbeat field updates simulate scheduler lifecycle."""

    def test_heartbeat_update(self, heartbeat):
        import os
        now = timezone.now()
        heartbeat.last_seen = now
        heartbeat.pid = os.getpid()
        heartbeat.save(update_fields=['last_seen', 'pid'])
        heartbeat.refresh_from_db()
        assert heartbeat.pid == os.getpid()
        assert abs((heartbeat.last_seen - now).total_seconds()) < 1

    def test_started_at_set_by_scheduler(self, heartbeat):
        now = timezone.now()
        heartbeat.started_at = now
        heartbeat.save(update_fields=['started_at'])
        heartbeat.refresh_from_db()
        assert heartbeat.started_at is not None

    def test_is_alive_check(self, heartbeat):
        """UI-side liveness check: last_seen within 60s."""
        heartbeat.last_seen = timezone.now()
        heartbeat.save(update_fields=['last_seen'])
        heartbeat.refresh_from_db()

        threshold = timezone.now() - timedelta(seconds=60)
        assert heartbeat.last_seen >= threshold

    def test_stale_heartbeat(self, heartbeat):
        """Stale heartbeat: last_seen > 60s ago."""
        heartbeat.last_seen = timezone.now() - timedelta(seconds=120)
        heartbeat.save(update_fields=['last_seen'])
        heartbeat.refresh_from_db()

        threshold = timezone.now() - timedelta(seconds=60)
        assert heartbeat.last_seen < threshold


# ---------------------------------------------------------------------------
# Stale lock recovery
# ---------------------------------------------------------------------------

class TestStaleRecovery:
    """Simulate stale lock recovery at scheduler startup."""

    def test_poster_stale_lock_recovery(self, config):
        """Poster stuck running at startup → reset to not running."""
        config.poster_running = True
        config.save(update_fields=['poster_running'])

        stale = DropshippingJobConfig.objects.filter(poster_running=True)
        assert stale.count() == 1

        for c in stale:
            c.poster_running = False
            c.save(update_fields=['poster_running'])

        config.refresh_from_db()
        assert config.poster_running is False

    def test_cleaner_stale_lock_recovery(self, cleaner_config):
        """Cleaner stuck running at startup → reset to not running."""
        cleaner_config.running = True
        cleaner_config.save(update_fields=['running'])

        stale = CleanerConfig.objects.filter(running=True)
        assert stale.count() == 1

        for cc in stale:
            cc.running = False
            cc.save(update_fields=['running'])

        cleaner_config.refresh_from_db()
        assert cleaner_config.running is False
