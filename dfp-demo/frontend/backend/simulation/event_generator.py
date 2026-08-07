"""
Event generator for the DFP simulation engine.

Wraps the existing get_normal_test_event / get_novel_test_event utilities and
publishes events to the dfp-events Kafka topic.  No direct dependency on the
TRAINING_FILE path — extract_user_profile uses source="auto" which tries the
user_training_events DB table first and falls back to the JSONL file.
"""

import json
import logging
import sys
from pathlib import Path

from kafka import KafkaProducer
from kafka.errors import KafkaError

# Make scripts/ importable from the backend simulation package.
# Resolved at import time so it works regardless of CWD.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dfp-demo/
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
for _p in (str(_SCRIPTS_DIR), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Patch the relative TRAINING_FILE path to absolute before any import resolves it,
# so the JSONL fallback in extract_user_profile works regardless of CWD.
import utils.shared.extract_user_profile as _eup  # noqa: E402  # pyright: ignore[reportMissingImports]

_eup.TRAINING_FILE = str(_PROJECT_ROOT / "data" / "input" / "train" / "azure_ad_train.jsonl")

from tests.test_novel_event import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    get_combined_novel_event,
    get_novel_test_event,
)
from utils.shared.extract_user_profile import (  # noqa: E402 # pyright: ignore[reportMissingImports]
    get_normal_test_event,
)

KAFKA_BROKER = "127.0.0.1:29092"
KAFKA_TOPIC = "dfp-events"

# Individual soft scenarios available for the simulation.
# impossible_travel is excluded — it's designed to produce physically impossible
# events which are better tested deliberately, not injected at random.
# location uses reachability-aware logic (picks the nearest reachable city at
# ≤800 km/h given elapsed time), so its timestamp always stays at or near `now`.
SOFT_SCENARIOS: tuple[str, ...] = ("app", "browser", "os", "device", "location")

# Subset of SOFT_SCENARIOS that support multi-scenario combination via
# get_combined_novel_event().  "location" is excluded because it requires
# timestamp manipulation and cannot be stacked with other mutations.
COMBO_SCENARIOS: frozenset[str] = frozenset({"app", "browser", "os", "device"})

# Pre-defined multi-scenario combinations.  The scheduler picks from this list
# to produce compound anomalies that change two feature dimensions at once.
MULTI_SCENARIO_COMBOS: tuple[tuple[str, ...], ...] = (
    ("app", "browser"),
    ("app", "device"),
    ("browser", "os"),
    ("os", "device"),
    ("app", "os"),
    ("browser", "device"),
    ("app", "browser", "os"),
    ("app", "browser", "device"),
)

logger = logging.getLogger(__name__)

_producer: KafkaProducer | None = None


def _get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    return _producer


def generate_event(
    user_id: str,
    is_novel: bool,
    scenario: str | list[str] | tuple[str, ...] | None = None,
) -> dict:
    """
    Generate a synthetic pipeline event for *user_id*.

    Args:
        user_id:   User email, e.g. "nancy.zabek@proseware.com"
        is_novel:  True → inject an anomaly scenario; False → normal behaviour
        scenario:  When *is_novel* is True, one of SOFT_SCENARIOS (str) **or** a
                   list/tuple of soft scenario names from SOFT_SCENARIOS for a
                   compound anomaly.  If omitted, the caller must pass is_novel=False.

    Returns:
        The raw event dict (Azure AD SignInLogs format).
    """
    if is_novel:
        if isinstance(scenario, (list, tuple)):
            # Validate each element against the combinable subset (location cannot be combined)
            bad = [s for s in scenario if s not in COMBO_SCENARIOS]
            if bad:
                raise ValueError(f"All scenarios in a list must be in {sorted(COMBO_SCENARIOS)}, got: {bad}")
            event = get_combined_novel_event(user_id, list(scenario))
        else:
            if scenario not in SOFT_SCENARIOS:
                raise ValueError(f"scenario must be one of {SOFT_SCENARIOS}, got {scenario!r}")
            event = get_novel_test_event(user_id, scenario)
    else:
        event = get_normal_test_event(user_id)
    return event


def publish_event(event: dict) -> bool:
    """
    Publish *event* to the dfp-events Kafka topic.

    Returns True on success, False on delivery failure.
    """
    try:
        producer = _get_producer()
        future = producer.send(KAFKA_TOPIC, event)
        # Use a short flush timeout so the scheduler thread is never blocked
        # for more than ~500 ms waiting for a Kafka ACK.  Messages are
        # buffered internally; a final flush in close_producer() drains any
        # remaining unsent records.
        producer.flush(timeout=0.5)
        future.get(timeout=5)
        return True
    except KafkaError as exc:
        logger.error("Kafka publish failed: %s", exc)
        # Reset producer so next call reconnects
        global _producer
        _producer = None
        return False


def close_producer() -> None:
    global _producer
    if _producer is not None:
        try:
            _producer.close(timeout=5)
        except Exception:
            pass
        _producer = None
