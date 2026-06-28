"""Dropship scheduler — main poll loop, thread lifecycle, heartbeat.

Runs as a standalone process via ``python manage.py run_dropship_scheduler``.
Owns all poster and cleaner threads; Django web app never spawns threads.

Design:
    - Single main loop (10s interval) handles both DB polling and heartbeat.
    - Heartbeat written every ~30s (every 3rd poll iteration).
    - One poster thread per enabled DropshippingJobConfig (parallel).
    - One cleaner thread per enabled CleanerConfig / source account.
    - Graceful shutdown on SIGTERM/SIGINT.

Worker state model (3-concept — Intent / Actual / Condition):
    - Intent:    ``enabled`` bool — user wants it running
    - Actual:    ``poster_running`` / ``running`` bool — thread is alive
    - Condition: ``disabled_reason`` — why system disabled it (empty = user)
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import timedelta
from threading import Event
from types import FrameType

from django.db import close_old_connections
from django.utils import timezone

from apps.posting.models import (
    CleanerConfig,
    DropshippingJobConfig,
    DropshipTargetURL,
    PostingLog,
    PostingLogLevel,
    SchedulerHeartbeat,
    GameVariant,
    GameVariantLimit,
)
from apps.posting.services.dropship.backoff import PauseRequired
from apps.posting.services.dropship.cleaner import cleaner_loop
from apps.posting.services.dropship.poster import poster_loop

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLL_INTERVAL = 10          # seconds between DB polls
HEARTBEAT_EVERY = 3         # write heartbeat every N polls (~30s)
SHUTDOWN_TIMEOUT = 30       # max seconds to wait for threads on shutdown


# ---------------------------------------------------------------------------
# DropshipScheduler
# ---------------------------------------------------------------------------

class DropshipScheduler:
    """Main scheduler — manages poster/cleaner threads via DB polling."""

    def __init__(self) -> None:
        # {config_id: (Thread, Event)}
        self._poster_threads: dict[int, tuple[threading.Thread, Event]] = {}
        # {cleaner_config_id: (Thread, Event)}
        self._cleaner_threads: dict[int, tuple[threading.Thread, Event]] = {}
        # Protects _poster_threads and _cleaner_threads against concurrent
        # access from the main poll loop and worker-thread finally blocks.
        self._threads_lock = threading.Lock()
        # Master shutdown signal
        self._shutdown_event = Event()
        self._poll_count = 0

    # -------------------------------------------------------------------
    # Public
    # -------------------------------------------------------------------

    def run(self) -> None:
        """Entry point — stale recovery, signal setup, main loop."""
        logger.info("Dropship scheduler starting (pid=%d)", os.getpid())

        self._install_signal_handlers()
        self._recover_stale_locks()
        self._ensure_heartbeat_row()

        logger.info(
            "Poll loop started (interval=%ds, heartbeat every ~%ds)",
            POLL_INTERVAL, POLL_INTERVAL * HEARTBEAT_EVERY,
        )

        try:
            while not self._shutdown_event.is_set():
                self._poll_count += 1

                try:
                    close_old_connections()
                    self._poll_once()
                except Exception:
                    logger.exception("Poll loop error (will retry next cycle)")

                # Heartbeat is independent of poll success — reflects process liveness
                if self._poll_count % HEARTBEAT_EVERY == 0:
                    try:
                        self._write_heartbeat()
                    except Exception:
                        logger.exception("Heartbeat write failed")

                self._shutdown_event.wait(timeout=POLL_INTERVAL)

        finally:
            self._graceful_shutdown()

    # -------------------------------------------------------------------
    # Signal handling
    # -------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — initiating graceful shutdown", sig_name)
        self._shutdown_event.set()

    # -------------------------------------------------------------------
    # Startup: stale lock recovery
    # -------------------------------------------------------------------

    def _recover_stale_locks(self) -> None:
        """Reset running flags left over from a previous crash."""
        count = 0

        # Poster stale locks
        for config in DropshippingJobConfig.objects.filter(poster_running=True):
            config.poster_running = False
            config.save(update_fields=['poster_running'])
            PostingLog.objects.create(
                task_name='scheduler',
                level=PostingLogLevel.WARNING,
                message=f"Poster stale lock recovered: config #{config.pk}",
            )
            logger.warning("Poster stale lock recovered: config #%d", config.pk)
            count += 1

        # Cleaner stale locks
        for cc in CleanerConfig.objects.filter(running=True):
            cc.running = False
            cc.save(update_fields=['running'])
            PostingLog.objects.create(
                task_name='scheduler',
                level=PostingLogLevel.WARNING,
                message=f"Cleaner stale lock recovered: source #{cc.source_account_id}",
            )
            logger.warning("Cleaner stale lock recovered: source #%d", cc.source_account_id)
            count += 1

        # Processing state flags (poster crash may leave fetching/posting stuck)
        stale_urls = DropshipTargetURL.objects.exclude(
            processing_state=DropshipTargetURL.PROC_IDLE,
        ).update(processing_state=DropshipTargetURL.PROC_IDLE)
        if stale_urls:
            logger.warning("Reset processing_state on %d target URL(s)", stale_urls)
            count += stale_urls

        logger.info("Stale lock recovery complete: %d worker(s) reset", count)

    # -------------------------------------------------------------------
    # Heartbeat
    # -------------------------------------------------------------------

    def _ensure_heartbeat_row(self) -> None:
        """Create or update the heartbeat row on startup."""
        now = timezone.now()
        SchedulerHeartbeat.objects.update_or_create(
            service_name='dropship',
            defaults={
                'last_seen': now,
                'pid': os.getpid(),
                'started_at': now,
            },
        )
        logger.info("Heartbeat row ensured (service_name='dropship')")

    def _write_heartbeat(self) -> None:
        """Update last_seen timestamp."""
        SchedulerHeartbeat.objects.filter(service_name='dropship').update(
            last_seen=timezone.now(),
            pid=os.getpid(),
        )

    # -------------------------------------------------------------------
    # Main poll
    # -------------------------------------------------------------------

    def _poll_once(self) -> None:
        """Single poll iteration — manage poster + cleaner threads."""
        self._poll_posters()
        self._poll_cleaners()

    # -------------------------------------------------------------------
    # Poster thread management
    # -------------------------------------------------------------------

    def _poll_posters(self) -> None:
        """Check enabled/disabled configs, start/stop poster threads."""

        # --- Enabled configs ---
        for config in DropshippingJobConfig.objects.filter(enabled=True).only(
            'id', 'poster_running',
        ):
            with self._threads_lock:
                thread_info = self._poster_threads.get(config.id)

            if thread_info is not None:
                thread, _stop = thread_info

                # Dead thread detection
                if not thread.is_alive():
                    logger.warning("Poster thread died: config #%d", config.id)
                    with self._threads_lock:
                        self._poster_threads.pop(config.id, None)
                    config.refresh_from_db()
                    if config.poster_running:
                        config.poster_running = False
                        config.enabled = False
                        config.disabled_reason = 'Thread terminated unexpectedly'
                        config.save(update_fields=[
                            'poster_running', 'enabled', 'disabled_reason',
                        ])
                    continue

            else:
                # No thread running — should we start one?
                config.refresh_from_db()
                if config.enabled and not config.poster_running:
                    reason = self._check_config_prerequisites(config)
                    if reason:
                        logger.warning(
                            "Config #%d not ready, disabling: %s",
                            config.id, reason,
                        )
                        config.enabled = False
                        config.disabled_reason = reason
                        config.save(update_fields=['enabled', 'disabled_reason'])
                    else:
                        self._start_poster_thread(config)

        # --- Disabled configs → stop running threads ---
        disabled_ids = set(
            DropshippingJobConfig.objects
            .filter(enabled=False)
            .values_list('id', flat=True)
        )
        with self._threads_lock:
            for config_id in list(self._poster_threads):
                if config_id in disabled_ids:
                    entry = self._poster_threads.get(config_id)
                    if entry is not None:
                        entry[1].set()  # stop_event

        # --- Deleted configs �� stop running threads ---
        existing_ids = set(
            DropshippingJobConfig.objects.values_list('id', flat=True)
        )
        with self._threads_lock:
            for config_id in list(self._poster_threads):
                if config_id not in existing_ids:
                    entry = self._poster_threads.get(config_id)
                    if entry is not None:
                        entry[1].set()  # stop_event
                    self._poster_threads.pop(config_id, None)

    @staticmethod
    def _check_config_prerequisites(config: DropshippingJobConfig) -> str | None:
        """Return an error reason if config is not ready to start, else None.

        Second-layer guard (mirrors API-level _check_config_ready) so that
        even if the DB is manually edited, the scheduler won't start a
        poster without URLs or variant limits.
        """
        has_urls = DropshipTargetURL.objects.filter(
            config=config, enabled=True,
        ).exists()
        if not has_urls:
            return 'No enabled target URLs'

        if GameVariant.objects.filter(game=config.game, type='platform').exists():
            has_limits = GameVariantLimit.objects.filter(
                store=config.store, variant__game=config.game,
            ).exists()
            if not has_limits:
                return f'No variant limits configured (game: {config.game.name})'

        return None

    def _start_poster_thread(self, config: DropshippingJobConfig) -> None:
        """Spawn a poster thread for the given config."""
        stop_event = Event()
        thread = threading.Thread(
            target=self._poster_thread_wrapper,
            args=(config.id, stop_event),
            name=f"poster-config-{config.id}",
            daemon=True,
        )
        with self._threads_lock:
            self._poster_threads[config.id] = (thread, stop_event)
        thread.start()
        logger.info("Poster thread started: config #%d", config.id)

    def _poster_thread_wrapper(self, config_id: int, stop_event: Event) -> None:
        """Poster thread lifecycle — wraps poster_loop with error handling."""
        config = None
        try:
            close_old_connections()

            config = (
                DropshippingJobConfig.objects
                .select_related(
                    'source_account', 'store', 'game',
                    'source_account__credential', 'store__credential',
                )
                .get(pk=config_id)
            )

            # ACTUAL → running
            config.poster_running = True
            config.save(update_fields=['poster_running'])

            logger.info("Poster loop entering: config #%d (%s)", config_id, config)
            poster_loop(config, stop_event)

        except PauseRequired as e:
            # Error threshold exceeded → disable with reason (INTENT + CONDITION)
            logger.warning("Config #%d disabled by system: %s", config_id, e.reason)
            if config:
                config.refresh_from_db()
                config.enabled = False
                config.disabled_reason = e.reason
                config.poster_running = False
                config.save(update_fields=['enabled', 'disabled_reason', 'poster_running'])
            PostingLog.objects.create(
                task_name='dropship_poster',
                level=PostingLogLevel.WARNING,
                message=f"Config #{config_id} disabled: {e.reason}",
                detail={'config_id': config_id, 'reason': e.reason},
                integration_account=config.store if config else None,
            )

        except Exception as e:
            # Unexpected crash → disable with reason
            logger.exception("Poster thread crashed: config #%d", config_id)
            if config:
                try:
                    config.refresh_from_db()
                    config.enabled = False
                    config.disabled_reason = f"Unexpected error: {str(e)[:200]}"
                    config.poster_running = False
                    config.save(update_fields=['enabled', 'disabled_reason', 'poster_running'])
                except Exception:
                    logger.exception("Failed to update config status after crash")
            PostingLog.objects.create(
                task_name='dropship_poster',
                level=PostingLogLevel.ERROR,
                message=f"Config #{config_id} crashed: {str(e)[:200]}",
                detail={'config_id': config_id, 'error': str(e)},
            )

        else:
            # Normal exit (stop_event set or disabled)
            logger.info("Poster thread stopped gracefully: config #%d", config_id)
            if config:
                config.refresh_from_db()
                config.poster_running = False
                config.save(update_fields=['poster_running'])

        finally:
            close_old_connections()
            with self._threads_lock:
                self._poster_threads.pop(config_id, None)
            logger.info("Poster thread exited: config #%d", config_id)

    # -------------------------------------------------------------------
    # Cleaner thread management
    # -------------------------------------------------------------------

    def _poll_cleaners(self) -> None:
        """Check CleanerConfig rows, start/stop cleaner threads per source account."""

        # --- Enabled cleaners ---
        for cc in CleanerConfig.objects.filter(enabled=True).only('id', 'running'):
            with self._threads_lock:
                thread_info = self._cleaner_threads.get(cc.id)

            if thread_info is not None:
                thread, _stop = thread_info

                # Dead thread detection
                if not thread.is_alive():
                    logger.warning("Cleaner thread died: CleanerConfig #%d", cc.id)
                    with self._threads_lock:
                        self._cleaner_threads.pop(cc.id, None)
                    cc.refresh_from_db()
                    if cc.running:
                        cc.running = False
                        cc.enabled = False
                        cc.disabled_reason = 'Thread terminated unexpectedly'
                        cc.save(update_fields=['running', 'enabled', 'disabled_reason'])
                    continue

            else:
                # No thread running — should we start one?
                cc.refresh_from_db()
                if cc.enabled and not cc.running:
                    self._start_cleaner_thread(cc)

        # --- Disabled cleaners → stop running threads ---
        disabled_ids = set(
            CleanerConfig.objects
            .filter(enabled=False)
            .values_list('id', flat=True)
        )
        with self._threads_lock:
            for cc_id in list(self._cleaner_threads):
                if cc_id in disabled_ids:
                    entry = self._cleaner_threads.get(cc_id)
                    if entry is not None:
                        entry[1].set()  # stop_event

        # --- Deleted cleaners → stop running threads ---
        existing_ids = set(
            CleanerConfig.objects.values_list('id', flat=True)
        )
        with self._threads_lock:
            for cc_id in list(self._cleaner_threads):
                if cc_id not in existing_ids:
                    entry = self._cleaner_threads.get(cc_id)
                    if entry is not None:
                        entry[1].set()  # stop_event
                    self._cleaner_threads.pop(cc_id, None)

    def _start_cleaner_thread(self, cc: CleanerConfig) -> None:
        """Spawn a cleaner thread for the given source account."""
        stop_event = Event()
        thread = threading.Thread(
            target=self._cleaner_thread_wrapper,
            args=(cc.id, stop_event),
            name=f"cleaner-source-{cc.source_account_id}",
            daemon=True,
        )
        with self._threads_lock:
            self._cleaner_threads[cc.id] = (thread, stop_event)
        thread.start()
        logger.info("Cleaner thread started: source #%d", cc.source_account_id)

    def _cleaner_thread_wrapper(self, cleaner_config_id: int, stop_event: Event) -> None:
        """Cleaner thread lifecycle — wraps cleaner_loop with error handling."""
        cc = None
        try:
            close_old_connections()

            cc = (
                CleanerConfig.objects
                .select_related('source_account', 'source_account__credential')
                .get(pk=cleaner_config_id)
            )

            # ACTUAL → running
            cc.running = True
            cc.save(update_fields=['running'])

            logger.info("Cleaner loop entering: source #%d", cc.source_account_id)
            cleaner_loop(cc, stop_event)

        except PauseRequired as e:
            # Error threshold exceeded → disable with reason
            logger.warning("Cleaner disabled by system (source #%d): %s",
                           cc.source_account_id if cc else '?', e.reason)
            if cc:
                cc.refresh_from_db()
                cc.enabled = False
                cc.disabled_reason = e.reason
                cc.running = False
                cc.save(update_fields=['enabled', 'disabled_reason', 'running'])
            PostingLog.objects.create(
                task_name='dropship_cleaner',
                level=PostingLogLevel.WARNING,
                message=f"Cleaner disabled: {e.reason}",
                detail={'cleaner_config_id': cleaner_config_id, 'reason': e.reason},
            )

        except Exception as e:
            # Unexpected crash → disable with reason
            logger.exception("Cleaner thread crashed: CleanerConfig #%d", cleaner_config_id)
            if cc:
                try:
                    cc.refresh_from_db()
                    cc.enabled = False
                    cc.disabled_reason = f"Unexpected error: {str(e)[:200]}"
                    cc.running = False
                    cc.save(update_fields=['enabled', 'disabled_reason', 'running'])
                except Exception:
                    logger.exception("Failed to update cleaner status after crash")

        else:
            # Normal exit (stop_event set or disabled)
            logger.info("Cleaner thread stopped gracefully: source #%d",
                        cc.source_account_id if cc else '?')
            if cc:
                cc.refresh_from_db()
                cc.running = False
                cc.save(update_fields=['running'])

        finally:
            close_old_connections()
            with self._threads_lock:
                self._cleaner_threads.pop(cleaner_config_id, None)
            logger.info("Cleaner thread exited: CleanerConfig #%d", cleaner_config_id)

    # -------------------------------------------------------------------
    # Graceful shutdown
    # -------------------------------------------------------------------

    def _graceful_shutdown(self) -> None:
        """Stop all threads and clean up statuses."""
        logger.info("Graceful shutdown initiated")

        # Snapshot thread registries under lock — workers may still be exiting
        with self._threads_lock:
            poster_snapshot = list(self._poster_threads.items())
            cleaner_snapshot = list(self._cleaner_threads.items())

        # Signal all poster threads
        for _config_id, (thread, stop_event) in poster_snapshot:
            stop_event.set()

        # Signal all cleaner threads
        for _cc_id, (thread, stop_event) in cleaner_snapshot:
            stop_event.set()

        # Wait for poster threads
        for config_id, (thread, _) in poster_snapshot:
            thread.join(timeout=SHUTDOWN_TIMEOUT)
            if thread.is_alive():
                logger.warning("Poster thread did not exit in time: config #%d", config_id)

        # Wait for cleaner threads
        for cc_id, (thread, _) in cleaner_snapshot:
            thread.join(timeout=SHUTDOWN_TIMEOUT)
            if thread.is_alive():
                logger.warning("Cleaner thread did not exit in time: CleanerConfig #%d", cc_id)

        # Force-reset any remaining running flags + mark heartbeat as dead
        try:
            close_old_connections()
            DropshippingJobConfig.objects.filter(poster_running=True).update(
                poster_running=False,
            )
            CleanerConfig.objects.filter(running=True).update(
                running=False,
            )
            # Set last_seen far in the past so UI immediately sees scheduler_alive=false
            SchedulerHeartbeat.objects.filter(service_name='dropship').update(
                last_seen=timezone.now() - timedelta(seconds=120),
            )
        except Exception:
            logger.exception("Failed to reset running flags during shutdown")

        logger.info("Graceful shutdown complete")
