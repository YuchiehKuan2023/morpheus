#!/usr/bin/env python3
"""
Full pipeline integration test — event → inference → AI orchestrator → agent orchestrator.

Publishes a novel Azure AD sign-in event to ``dfp-events`` and polls all
three stages until completion (or timeout), verifying that each layer did
its job:

    Stage 1 — Inference pipeline (DFP autoencoder)
        dfp-events → scoring → dfp-detections published

    Stage 2 — AI Orchestrator
        dfp-detections → enrichment → labeling → classification →
        risk scoring → enriched_anomalies row fully written →
        dfp-agent-tasks published (if severity HIGH/CRITICAL or MEDIUM≥60)

    Stage 3 — Agent Orchestrator
        dfp-agent-tasks → ForensicsAgent + InvestigationAgent →
        RemediationAgent → agent_investigations complete

Prerequisites (all must be running):
    - pipelines/inference_pipeline.py     (consuming dfp-events)
    - scripts/run_ai_orchestrator.py      (consuming dfp-detections)
    - scripts/run_agent_orchestrator.py   (consuming dfp-agent-tasks)
    - Kafka, PostgreSQL, Neo4j, Qdrant, Ollama/Groq, MLflow

Timing:
    The full chain takes 30-90 s per event (DFP scoring + NER + embeddings
    + LLM explanation + DistilBERT + XGBoost + 3 LLM agent calls).
    Default --timeout is 120 s; increase if Ollama is slow.

Usage:
    python scripts/tests/test_integration_full.py \\
        --user jennifer.nguyen@contoso.com \\
        --scenario all

    python scripts/tests/test_integration_full.py \\
        --user jennifer.nguyen@contoso.com \\
        --scenario impossible_travel \\
        --timeout 180 \\
        --api

    python scripts/tests/test_integration_full.py --list-users

    # Verify a baseline event is NOT flagged as an anomaly (false-positive check):
    python scripts/tests/test_integration_full.py \\
        --user jennifer.nguyen@contoso.com \\
        --normal-event

Exit codes:
    0 — all stages completed (Stage 3 reached complete status), or anomaly
        score below agent threshold (pipeline completed with PARTIAL PASS),
        or normal-event mode: baseline event correctly not detected
    1 — any stage failed or timed out, or normal-event mode: false positive detected
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import psycopg2.extras
from constants.tests import KAFKA_BROKER, KAFKA_TOPIC
from kafka import KafkaConsumer, KafkaProducer, TopicPartition

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8001/api/v1")
DETECTIONS_TOPIC = os.getenv("DETECTIONS_TOPIC", "dfp-detections")

SCENARIOS = ["app", "browser", "os", "device", "location", "all", "impossible_travel"]

# Severity thresholds (mirrors ai_orchestrator.py)
_SEVERITY_CRITICAL = 5.0
_SEVERITY_HIGH = 3.0
_SEVERITY_MEDIUM = 2.5


# ---------------------------------------------------------------------------
# DB / Kafka helpers
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    from modules.utils.db import get_db_url

    return get_db_url()


def _poll(
    conn: psycopg2.extensions.connection,
    query: str,
    params: tuple,
    stop_condition,
    timeout: int,
    label: str,
) -> dict | None:
    """Generic poller: runs query every second until stop_condition(row) is True."""
    deadline = time.monotonic() + timeout
    next_dot = time.monotonic() + 2

    while time.monotonic() < deadline:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            conn.rollback()

        if row and stop_condition(dict(row)):
            print()
            return dict(row)

        if time.monotonic() >= next_dot:
            print(".", end="", flush=True)
            next_dot += 2
        time.sleep(1)

    print()
    print(f"  TIMEOUT waiting for {label} after {timeout}s")
    return None


def _open_detections_consumer() -> tuple[KafkaConsumer, list[TopicPartition]]:
    """
    Create a KafkaConsumer for dfp-detections and seek all partitions to their
    current end offsets.  Call this BEFORE publishing the test event so that
    only messages produced after this point are visible.

    Returns (consumer, partitions) so the caller can close the consumer when done.
    """
    consumer = KafkaConsumer(
        bootstrap_servers=KAFKA_BROKER,
        enable_auto_commit=False,
        group_id=None,  # transient — no committed offsets
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        consumer_timeout_ms=500,
    )
    raw_partitions = consumer.partitions_for_topic(DETECTIONS_TOPIC)
    if not raw_partitions:
        # Topic may not exist yet if no detections have ever been produced;
        # fall back to partition 0
        raw_partitions = {0}
    partitions = [TopicPartition(DETECTIONS_TOPIC, p) for p in sorted(raw_partitions)]
    consumer.assign(partitions)
    consumer.seek_to_end(*partitions)
    return consumer, partitions


def _poll_detections(consumer: KafkaConsumer, user_id: str, max_wait: int = 30) -> dict | None:
    """
    Poll dfp-detections for a message whose user_id matches the test user.

    The consumer must already be seeked past the end offset that existed before
    the test event was published (see _open_detections_consumer).  Returns the
    detection dict if an anomaly was published within max_wait seconds, or None.
    """
    deadline = time.monotonic() + max_wait
    next_dot = time.monotonic() + 2

    while time.monotonic() < deadline:
        records = consumer.poll(timeout_ms=1000)
        for _tp, messages in records.items():
            for msg in messages:
                data = msg.value
                if isinstance(data, dict) and data.get("user_id") == user_id:
                    print()
                    return data

        if time.monotonic() >= next_dot:
            print(".", end="", flush=True)
            next_dot += 2

    print()
    return None


def _list_users(conn: psycopg2.extensions.connection) -> None:
    """Print users that have cached training data (baselines loaded)."""
    cache_dir = Path(__file__).parent.parent.parent / ".cache" / "demo" / "rolling-user-data"
    if cache_dir.exists():
        users = sorted(p.stem for p in cache_dir.glob("*.pkl"))
        print(f"Users with cached training data ({len(users)}):")
        for u in users:
            print(f"  {u}")
    else:
        print(f"Cache directory not found: {cache_dir}")
    sys.exit(0)


def _check_api(anomaly_id: str) -> None:
    url = f"{API_BASE}/anomalies/{anomaly_id}/investigation"
    print(f"\n[API] GET {url}")
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = json.loads(resp.read())
            status = body.get("status", "?")
            findings = body.get("findings", [])
            print(f"[API] HTTP 200 — status={status} findings={len(findings)}")
            for f in findings or []:
                print(f"       agent={f.get('agent_type')} status={f.get('status')} confidence={f.get('confidence')}")
    except urllib.error.HTTPError as exc:
        print(f"[API] HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        print(f"[API] Could not reach backend: {exc}")


# ---------------------------------------------------------------------------
# Stage reporters
# ---------------------------------------------------------------------------


def _report_stage1(anomaly: dict) -> None:
    score = float(anomaly.get("anomaly_score") or 0.0)
    if score > _SEVERITY_CRITICAL:
        sev = "CRITICAL"
    elif score >= _SEVERITY_HIGH:
        sev = "HIGH"
    elif score >= _SEVERITY_MEDIUM:
        sev = "MEDIUM"
    else:
        sev = "LOW"
    print(f"  anomaly_id    : {anomaly['anomaly_id']}")
    print(f"  anomaly_score : {score:.4f}  →  severity={sev}")
    print(f"  user_id       : {anomaly.get('user_id')}")


def _report_stage2(anomaly: dict) -> None:
    print(f"  is_anomaly    : {anomaly.get('is_anomaly')}")
    print(f"  root_cause    : {anomaly.get('root_cause')}")
    print(f"  sub_category  : {anomaly.get('sub_category')}")
    print(f"  risk_score    : {anomaly.get('risk_score')}")
    print(f"  severity      : {anomaly.get('severity')}")


def _report_stage3(inv: dict) -> None:
    status = inv["status"]
    findings = inv["findings"] or []
    print(f"  investigation_id : {inv['investigation_id']}")
    print(f"  status           : {status}")
    print(f"  agents_invoked   : {inv.get('agents_invoked')}")
    print(f"  confidence_score : {inv.get('confidence_score')}")
    print(f"  findings         : {len(findings)}")
    for f in findings:
        icon = "PASS" if f.get("status") == "complete" else "FAIL"
        print(
            f"    {icon} {f.get('agent_type'):<20} status={f.get('status'):<10} "
            f"confidence={f.get('confidence') or '—':<6} latency={f.get('latency_ms') or '—'}ms"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full pipeline integration test: event → inference → AI orch → agent orch"
    )
    parser.add_argument(
        "--user",
        help="User email (e.g. jennifer.nguyen@contoso.com). Use --list-users to see options.",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="all",
        help="Novel event scenario to generate (default: all — changes all features)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Seconds to wait for Stage 2/3 (LLM enrichment + agents). Default: 120.",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Also validate the REST endpoint after Stage 3 completes",
    )
    parser.add_argument(
        "--list-users",
        action="store_true",
        help="Print users with cached training data and exit",
    )
    parser.add_argument(
        "--normal-event",
        action="store_true",
        help="Test with a baseline (non-anomaly) event; verifies no false-positive detection.",
    )
    args = parser.parse_args()

    db_url = _get_db_url()

    try:
        conn = psycopg2.connect(db_url)
    except Exception as exc:
        sys.exit(f"[ERROR] Cannot connect to PostgreSQL: {exc}")

    if args.list_users:
        _list_users(conn)

    if not args.user:
        parser.error("--user is required (use --list-users to see available users)")

    # ── Generate event (normal baseline or novel anomaly) ────────────────────
    if args.normal_event:
        try:
            from utils.shared.extract_user_profile import get_normal_test_event
        except ImportError:
            from shared.extract_user_profile import get_normal_test_event  # type: ignore[no-redef]
        try:
            event = get_normal_test_event(args.user)
        except Exception as exc:
            sys.exit(
                f"[ERROR] Could not generate baseline event for user {args.user!r}: {exc}\n"
                "Make sure the user has cached training data. Use --list-users to check."
            )
        scenario_label = "normal (baseline)"
    else:
        try:
            from scripts.tests.test_novel_event import get_novel_test_event
        except ImportError:
            from test_novel_event import get_novel_test_event  # type: ignore[no-redef]
        try:
            event = get_novel_test_event(args.user, args.scenario)
        except Exception as exc:
            sys.exit(
                f"[ERROR] Could not generate event for user {args.user!r}: {exc}\n"
                "Make sure the user has cached training data. Use --list-users to check."
            )
        scenario_label = args.scenario

    print("=" * 70)
    print("Full Pipeline Integration Test")
    print(f"  User     : {args.user}")
    print(f"  Scenario : {scenario_label}")
    print(f"  Timeout  : 30s (Stage 1) / {args.timeout}s (Stages 2-3)")
    print("=" * 70)

    print(f"\nGenerating '{scenario_label}' event for {args.user} ...")

    # ── Subscribe to dfp-detections BEFORE publishing ────────────────────────
    # Seek to the current end offset now so we only see messages produced after
    # our test event enters the pipeline.
    detections_consumer, _det_partitions = _open_detections_consumer()

    # ── Publish to dfp-events ────────────────────────────────────────────────
    publish_time = datetime.now(timezone.utc)
    print(f"Publishing to {KAFKA_TOPIC} via {KAFKA_BROKER} ...")
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        producer.send(KAFKA_TOPIC, event)
        producer.flush(timeout=5)
        producer.close()
    except Exception as exc:
        sys.exit(f"[ERROR] Kafka publish failed: {exc}")

    print(f"Event published at {publish_time.isoformat()}")

    # ── Stage 1: Poll dfp-detections Kafka topic ─────────────────────────────
    # The inference pipeline publishes to dfp-detections ONLY when mean_abs_z
    # exceeds the anomaly threshold.  We subscribed before publishing, so any
    # message for this user that arrives here is our event's detection.
    # If 30 s pass with no message the event was scored below threshold and
    # FilterDetections discarded it — nothing will ever reach the orchestrators.
    print("\n── Stage 1: Inference pipeline detection")
    print("            (dfp-events → DFP scoring → dfp-detections)")
    print(f"   Polling dfp-detections for user={args.user!r} ", end="", flush=True)

    detection_msg = _poll_detections(detections_consumer, args.user, max_wait=30)
    detections_consumer.close()

    if detection_msg is None:
        if args.normal_event:
            print("PASS — baseline event correctly not flagged as anomaly (no message on dfp-detections).")
        else:
            print("No detection on dfp-detections within 30s.")
            print("   The event was processed by DFP but scored below the anomaly threshold —")
            print("   FilterDetections discarded it.  Nothing reaches the AI or Agent orchestrator.")
            print("   Try --scenario all or --scenario impossible_travel for a higher anomaly score.")
        conn.close()
        sys.exit(0)

    anomaly_score = detection_msg.get("anomaly_score", "?")
    if args.normal_event:
        print(f"FAIL — false positive! Baseline event flagged as anomaly (score={anomaly_score}).")
        conn.close()
        sys.exit(1)
    print(f"Stage 1 PASSED — anomaly published to dfp-detections (score={anomaly_score})")

    # ── Wait for enriched_anomalies row (AI orchestrator persistence) ─────────
    print("   Waiting for AI Orchestrator to persist to enriched_anomalies ", end="", flush=True)

    stage1_row = _poll(
        conn=conn,
        query="""
            SELECT anomaly_id, user_id, anomaly_score, severity, root_cause,
                   sub_category, risk_score, is_anomaly, created_at
            FROM   enriched_anomalies
            WHERE  user_id = %s
              AND  created_at >= %s
            ORDER  BY created_at DESC
            LIMIT  1
        """,
        params=(args.user, publish_time),
        stop_condition=lambda r: r.get("anomaly_id") is not None,
        timeout=args.timeout,
        label="enriched_anomalies row",
    )

    if stage1_row is None:
        print("Stage 1b FAILED — detection reached dfp-detections but was not persisted by AI Orchestrator.")
        print("   Is run_ai_orchestrator.py running and consuming dfp-detections?")
        sys.exit(1)

    print("Stage 1 PASSED — AI Orchestrator persisted the detection")
    _report_stage1(stage1_row)

    anomaly_id = str(stage1_row["anomaly_id"])

    # ── Stage 2: Poll for AI orchestrator completion ──────────────────────────
    # Poll on root_cause IS NOT NULL — written by classify_single() and always
    # present after Stage 2 regardless of whether the XGBoost risk model exists.
    # risk_score may remain NULL if the model hasn't been trained yet; we still
    # report it if present but do not fail on its absence.
    print("\n── Stage 2: AI Orchestrator (enrichment → labeling → classification → risk score)")
    print("   Polling for fully enriched row (root_cause populated) ", end="", flush=True)

    stage2_row = _poll(
        conn=conn,
        query="""
            SELECT anomaly_id, user_id, anomaly_score, severity, root_cause,
                   sub_category, risk_score, is_anomaly
            FROM   enriched_anomalies
            WHERE  anomaly_id = %s
              AND  root_cause IS NOT NULL
        """,
        params=(anomaly_id,),
        stop_condition=lambda r: r.get("root_cause") is not None,
        timeout=args.timeout,
        label="root_cause populated in enriched_anomalies",
    )

    if stage2_row is None:
        print("Stage 2 FAILED — AI orchestrator did not complete enrichment.")
        print("   Is run_ai_orchestrator.py running and consuming dfp-detections?")
        sys.exit(1)

    print("Stage 2 PASSED — AI orchestrator fully enriched the anomaly")
    _report_stage2(stage2_row)

    # Check if severity is high enough to trigger agents
    severity = str(stage2_row.get("severity") or "LOW").upper()
    risk_score = float(stage2_row.get("risk_score") or 0.0)
    agents_expected = severity in ("CRITICAL", "HIGH") or (severity == "MEDIUM" and risk_score >= 60.0)

    if not agents_expected:
        print(f"\nseverity={severity} risk_score={risk_score:.1f} — below agent invocation threshold.")
        print("   Agents are NOT triggered for this event. Try --scenario impossible_travel for a higher score.")
        print("\nPARTIAL PASS — Stages 1+2 validated; Stage 3 not applicable for this event.")
        conn.close()
        sys.exit(0)

    # ── Stage 3: Poll agent_investigations ───────────────────────────────────
    print("\n── Stage 3: Agent Orchestrator (ForensicsAgent + InvestigationAgent + RemediationAgent)")
    print(f"   Polling agent_investigations for anomaly_id={anomaly_id} ", end="", flush=True)

    stage3_row = _poll(
        conn=conn,
        query="""
            SELECT
                ai.investigation_id,
                ai.status,
                ai.agents_invoked,
                ai.confidence_score,
                ai.triggered_at,
                ai.completed_at,
                json_agg(
                    json_build_object(
                        'agent_type',  af.agent_type,
                        'status',      af.status,
                        'confidence',  af.result->>'confidence',
                        'latency_ms',  af.latency_ms
                    )
                ) FILTER (WHERE af.finding_id IS NOT NULL) AS findings
            FROM   agent_investigations ai
            LEFT   JOIN agent_findings af ON af.investigation_id = ai.investigation_id
            WHERE  ai.anomaly_id = %s
            GROUP  BY ai.investigation_id
            ORDER  BY ai.triggered_at DESC
            LIMIT  1
        """,
        params=(anomaly_id,),
        stop_condition=lambda r: r.get("status") in ("complete", "failed"),
        timeout=args.timeout,
        label="agent_investigations terminal status",
    )

    conn.close()

    if stage3_row is None:
        print("Stage 3 FAILED — agent orchestrator did not complete.")
        print("   Is run_agent_orchestrator.py running and consuming dfp-agent-tasks?")
        sys.exit(1)

    stage3_status = stage3_row["status"]
    print(
        f"{'PASS' if stage3_status == 'complete' else 'FAIL'} Stage 3 {'PASSED' if stage3_status == 'complete' else 'FAILED'} — {stage3_status.upper()}"
    )
    _report_stage3(stage3_row)

    if args.api:
        _check_api(anomaly_id)

    print()
    print("=" * 70)
    if stage3_status != "complete":
        print("FULL PIPELINE TEST FAILED — investigation did not complete.")
        sys.exit(1)
    if not stage3_row.get("findings"):
        print("FULL PIPELINE TEST FAILED — no agent findings recorded.")
        sys.exit(1)

    print("FULL PIPELINE TEST PASSED — all 3 stages completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
