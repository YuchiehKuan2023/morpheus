"""
Simulation manager — singleton that owns the scheduler thread and tracker pool.

Usage (from routes):
    from simulation import get_manager

    manager = get_manager()
    run_id  = manager.start(users=["alice@..."], speed="demo")
    status  = manager.status()
    summary = manager.stop()
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .event_generator import close_producer
from .simulation_scheduler import SimulationScheduler

logger = logging.getLogger(__name__)

_MAX_TRACKER_WORKERS = 20  # one per concurrent active session


class SimulationManager:
    """
    Thread-safe singleton that manages the simulation lifecycle.

    start() → stop() is one *run*.  After stop() the manager is ready to
    accept another start() call (new run_id each time).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._run_id: UUID | None = None
        self._started_at: datetime | None = None
        self._stop_event = threading.Event()
        self._scheduler: SimulationScheduler | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._counters: dict = {}
        self._counters_lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self, users: list[str], speed: str) -> UUID:
        """
        Start a simulation run.

        Args:
            users: List of user_id strings to simulate.
            speed: One of 'realistic' | 'fast' | 'demo'.

        Returns:
            The UUID run_id for this run (used to filter SSE stream).

        Raises:
            RuntimeError: If a run is already in progress.
        """
        with self._lock:
            if self._running:
                raise RuntimeError("A simulation run is already in progress. Call stop() first.")

            self._run_id = uuid4()
            self._started_at = datetime.now(timezone.utc)
            self._stop_event = threading.Event()
            self._counters = {
                "events_sent": 0,
                "anomalies_detected": 0,
                "clean_count": 0,
                "novel_sent": 0,
                "active_trackers": 0,
            }
            self._executor = ThreadPoolExecutor(
                max_workers=_MAX_TRACKER_WORKERS,
                thread_name_prefix="sim-tracker",
            )
            self._scheduler = SimulationScheduler(
                run_id=self._run_id,
                users=users,
                speed=speed,
                stop_event=self._stop_event,
                executor=self._executor,
                counters=self._counters,
                counters_lock=self._counters_lock,
            )
            self._scheduler.start()
            self._running = True

        logger.info("Simulation run %s started (users=%d, speed=%s)", self._run_id, len(users), speed)
        return self._run_id

    def stop(self) -> dict:
        """
        Stop the current simulation run.

        Returns a summary dict.  Safe to call even if not running.
        """
        with self._lock:
            if not self._running:
                return {"error": "No simulation run in progress."}

            self._stop_event.set()

            if self._scheduler and self._scheduler.is_alive():
                self._scheduler.join(timeout=10)

            if self._executor:
                self._executor.shutdown(wait=False, cancel_futures=False)
                self._executor = None

            close_producer()

            summary = {
                "run_id": str(self._run_id),
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "stopped_at": datetime.now(timezone.utc).isoformat(),
                **self._counters,
            }
            self._running = False
            self._scheduler = None

        logger.info("Simulation run %s stopped: %s", self._run_id, summary)
        return summary

    def status(self) -> dict:
        """Return the current run status (safe to call at any time)."""
        with self._lock:
            with self._counters_lock:
                counters = dict(self._counters)
            return {
                "running": self._running,
                "run_id": str(self._run_id) if self._run_id else None,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "events_sent": counters.get("events_sent", 0),
                "anomalies_detected": counters.get("anomalies_detected", 0),
                "clean_count": counters.get("clean_count", 0),
                "novel_sent": counters.get("novel_sent", 0),
                "active_trackers": counters.get("active_trackers", 0),
            }

    @property
    def run_id(self) -> UUID | None:
        return self._run_id

    @property
    def is_running(self) -> bool:
        return self._running


# ── Module-level singleton ─────────────────────────────────────────────────────

_manager: SimulationManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> SimulationManager:
    """Return the process-wide SimulationManager singleton (lazy init)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SimulationManager()
    return _manager
