"""
Simulation scheduler — produces events in a realistic per-user cadence.

Runs as a single background daemon thread.  For each user it maintains an
independent "next event time", seeded with random jitter so events from
different users are spread out rather than firing simultaneously.

Cadence model
─────────────
  • Peak hours (08:00–19:00 local simulation time): mean inter-event interval 15 min
  • Off-hours: mean 45 min, with 80 % suppression (most off-hour ticks are skipped)
  • Speed multipliers collapse the intervals:
      realistic = 1×  (true-to-life, runs for hours)
      fast      = 10× (compressed, ~15 min between events → ~90 s)
      demo      = 60× (very fast, events fire every ~15 s)

Novel events
────────────
  5 % of events are novel.  Only soft scenarios are used:
  app / browser / os / device  — never location or all, to avoid pipeline
  rejection before the AI stage can process the event.
"""

import logging
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg2

from .event_generator import MULTI_SCENARIO_COMBOS, SOFT_SCENARIOS, generate_event, publish_event
from .stage_tracker import StageTracker

logger = logging.getLogger(__name__)

PEAK_HOURS = range(8, 19)  # 08:00–18:59
PEAK_MEAN_MINUTES = 15
OFF_MEAN_MINUTES = 45
OFF_SUPPRESSION_PROB = 0.80
NOVEL_PROB = 0.50  # 50 % during testing — revert to 0.05 for production

SPEED_DIVISORS = {
    "realistic": 1.0,
    "fast": 10.0,
    "demo": 60.0,
}


def _db_params() -> dict:
    from modules.utils.db import get_db_params

    return get_db_params()


def _insert_session(conn, run_id: UUID, session_id: UUID, user_id: str, event_type: str, scenario: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO simulation_sessions
                (session_id, run_id, user_id, event_type, scenario)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (str(session_id), str(run_id), user_id, event_type, scenario),
        )
    conn.commit()


class SimulationScheduler(threading.Thread):
    """
    Produces events for *users* in a realistic cadence until *stop_event* is set.

    Each dispatched event gets its own StageTracker submitted to *executor*.
    Call-outs (events_sent / anomalies_detected / clean_count / active_trackers)
    are updated on the shared *counters* dict (keys as above) under *counters_lock*.
    """

    def __init__(
        self,
        run_id: UUID,
        users: list[str],
        speed: str,
        stop_event: threading.Event,
        executor: ThreadPoolExecutor,
        counters: dict,
        counters_lock: threading.Lock,
    ):
        super().__init__(daemon=True, name="sim-scheduler")
        self.run_id = run_id
        self.users = users
        self.speed = speed
        self.divisor = SPEED_DIVISORS.get(speed, 1.0)
        self.stop_event = stop_event
        self.executor = executor
        self.counters = counters
        self.counters_lock = counters_lock
        self.db_params = _db_params()
        self._active_trackers: list[tuple[Future, StageTracker]] = []
        # Per-user lock: maps user_id → True while a tracker is running for
        # that user.  Prevents two events for the same user from landing in
        # the same Kafka batch, which would cause DFP to silently discard all
        # but the last event (last_row_df = detections.iloc[[-1]]).
        self._user_active: set[str] = set()

    def _next_interval(self) -> float:
        """Return seconds until the next event for a user.

        The exponential distribution has high variance (stddev == mean), which
        can produce tail draws of 5-10× the mean.  For fast/demo modes this
        causes multi-minute silences that are confusing in demos.  Cap the draw
        at 2× the effective mean so at most ~86% of samples are unchanged while
        the worst-case gap is bounded.

        In fast/demo mode always use the peak mean regardless of wall-clock time
        so events arrive at the advertised cadence no matter when you run.
        """
        if self.speed != "realistic":
            mean_sec = PEAK_MEAN_MINUTES * 60
        else:
            hour = datetime.now().hour
            mean_sec = PEAK_MEAN_MINUTES * 60 if hour in PEAK_HOURS else OFF_MEAN_MINUTES * 60
        raw = random.expovariate(1.0 / mean_sec) / self.divisor
        cap = 2.0 * mean_sec / self.divisor
        return min(raw, cap)

    def _should_suppress_off_hours(self) -> bool:
        # Off-hours suppression only makes sense in realistic mode.
        # In fast/demo mode the user explicitly wants a fast cadence regardless
        # of wall-clock time, so never suppress.
        if self.speed != "realistic":
            return False
        hour = datetime.now().hour
        if hour not in PEAK_HOURS:
            return random.random() < OFF_SUPPRESSION_PROB
        return False

    def _count_active_trackers(self) -> int:
        done_users = {t.user_id for f, t in self._active_trackers if f.done()}
        self._active_trackers = [(f, t) for f, t in self._active_trackers if not f.done()]
        active_users = {t.user_id for _, t in self._active_trackers}
        # Release per-user lock for any user whose tracker just finished.
        self._user_active -= done_users - active_users
        return len(self._active_trackers)

    def run(self) -> None:
        # Initialise per-user next-event times with uniform jitter so they
        # don't all fire at t=0.
        next_event_times: dict[str, float] = {}
        for user in self.users:
            jitter = random.uniform(0, self._next_interval())
            next_event_times[user] = time.monotonic() + jitter

        conn = psycopg2.connect(**self.db_params)
        try:
            while not self.stop_event.is_set():
                for user in self.users:
                    if self.stop_event.is_set():
                        break
                    # Refresh now per-user so that a blocking dispatch for one
                    # user doesn't make subsequent users appear overdue all at
                    # once on the next outer-loop tick.
                    now = time.monotonic()
                    if now < next_event_times[user]:
                        continue

                    # Schedule next event before doing any work
                    next_event_times[user] = now + self._next_interval()

                    if self._should_suppress_off_hours():
                        continue

                    self._dispatch_event(conn, user)

                # Sleep a short tick; actual resolution depends on divisor
                tick = max(0.1, 1.0 / self.divisor)
                self.stop_event.wait(timeout=tick)
        finally:
            conn.close()

    def _dispatch_event(self, conn, user_id: str) -> None:
        # Prune finished trackers first so _user_active is up to date.
        self._count_active_trackers()
        if user_id in self._user_active:
            logger.debug(
                "Skipping dispatch for %s — tracker already active (prevents same-user batch conflict in DFP)",
                user_id,
            )
            return

        is_novel = random.random() < NOVEL_PROB
        # 30 % of novel events use a multi-feature combination; the rest pick a
        # single soft scenario.  This matches a more realistic threat model where
        # an attacker sometimes brings their own device AND browser simultaneously.
        scenario: str | tuple[str, ...] | None
        if is_novel:
            if random.random() < 0.30:
                scenario = random.choice(MULTI_SCENARIO_COMBOS)
                scenario_label: str | None = "+".join(scenario)  # type: ignore[arg-type]
            else:
                scenario = random.choice(SOFT_SCENARIOS)
                scenario_label = scenario
        else:
            scenario = None
            scenario_label = None
        session_id = uuid4()
        sent_at = datetime.now(timezone.utc)

        try:
            event = generate_event(user_id, is_novel, scenario)
        except Exception as exc:
            logger.warning("Event generation failed for %s: %s", user_id, exc)
            return

        # Tag the event with the simulation session_id so the stage tracker can
        # correlate this specific Kafka message to its enriched_anomalies row.
        event["_simulation_session_id"] = str(session_id)

        success = publish_event(event)
        if not success:
            logger.warning("Kafka publish failed for session %s", session_id)
            return

        event_type = "novel" if is_novel else "clean"
        try:
            _insert_session(conn, self.run_id, session_id, user_id, event_type, scenario_label)
        except Exception as exc:
            logger.error("DB insert failed for session %s: %s", session_id, exc)
            conn.rollback()
            return

        tracker = StageTracker(session_id, user_id, sent_at, self.db_params)
        future = self.executor.submit(tracker.run)
        self._active_trackers.append((future, tracker))
        self._user_active.add(user_id)

        with self.counters_lock:
            self.counters["events_sent"] += 1
            if is_novel:
                self.counters["novel_sent"] = self.counters.get("novel_sent", 0) + 1
            else:
                self.counters["clean_count"] += 1
            self.counters["active_trackers"] = self._count_active_trackers()

        logger.debug(
            "Dispatched %s event for %s [session=%s, scenario=%s]",
            event_type,
            user_id,
            str(session_id)[:8],
            scenario_label,
        )
