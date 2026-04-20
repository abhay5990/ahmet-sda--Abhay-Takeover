"""Small concurrency helpers owned by payload_pipeline."""

from __future__ import annotations

import atexit
import threading
from concurrent.futures import ThreadPoolExecutor


_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def get_executor(max_workers: int = 10) -> ThreadPoolExecutor:
    """Return the shared thread-pool executor, creating it lazily on first call."""
    global _executor
    if _executor is None:
        with _lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="payload_pipeline",
                )
                atexit.register(_executor.shutdown, wait=False)
    return _executor


def shutdown_executor(*, wait: bool = True) -> None:
    """Shut down the shared executor explicitly (e.g. during hot-reload)."""
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=wait)
            _executor = None
