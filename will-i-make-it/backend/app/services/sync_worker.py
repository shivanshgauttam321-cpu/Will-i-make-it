"""
Background Synchronization Worker
==================================
Lightweight background thread that periodically polls and processes the Transactional
Outbox, synchronizing primary application database changes to Neo4j Aura.
Zero external infrastructure dependencies (No Redis or Kafka needed). Compatible with
standard Render web services.
"""
from __future__ import annotations

import threading
import time
import logging
from typing import Optional

from app.services.graph_sync_service import process_outbox_batch

logger = logging.getLogger(__name__)

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_trigger_event = threading.Event()
_is_running = False


def _worker_loop(interval_seconds: float = 5.0) -> None:
    global _is_running
    _is_running = True
    logger.info(f"[SyncWorker] Background outbox sync worker started (polling every {interval_seconds}s).")

    while not _stop_event.is_set():
        try:
            # Process pending batch
            process_outbox_batch(limit=25)
        except Exception as e:
            logger.error(f"[SyncWorker] Error in sync worker loop: {e}", exc_info=True)

        # Wait for either interval timeout or an explicit wake-up trigger
        _trigger_event.wait(timeout=interval_seconds)
        _trigger_event.clear()

    _is_running = False
    logger.info("[SyncWorker] Background outbox sync worker terminated gracefully.")


def start_sync_worker(interval_seconds: float = 5.0) -> None:
    """Start the background synchronization worker daemon thread."""
    global _worker_thread, _stop_event
    if _worker_thread is not None and _worker_thread.is_alive():
        return

    _stop_event.clear()
    _trigger_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        args=(interval_seconds,),
        name="Neo4jOutboxSyncWorker",
        daemon=True,
    )
    _worker_thread.start()


def stop_sync_worker(timeout: float = 3.0) -> None:
    """Signal worker to stop and wait for termination."""
    global _worker_thread, _stop_event
    if _worker_thread is not None and _worker_thread.is_alive():
        _stop_event.set()
        _trigger_event.set()
        _worker_thread.join(timeout=timeout)
        _worker_thread = None


def trigger_sync() -> None:
    """Wake up the worker immediately for instant synchronization."""
    _trigger_event.set()


def is_worker_active() -> bool:
    return _worker_thread is not None and _worker_thread.is_alive() and _is_running
