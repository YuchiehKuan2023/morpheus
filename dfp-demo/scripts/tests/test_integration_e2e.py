#!/usr/bin/env python3
"""
End-to-end integration test for the Agent Orchestrator.

Bypasses the inference pipeline and AI orchestrator by publishing a task
message directly to ``dfp-agent-tasks``, then polls the DB to confirm that
the AgentOrchestrator created an investigation row and at least one finding.

Prerequisites (must all be running):
    - run_agent_orchestrator.py   (consuming dfp-agent-tasks)
    - PostgreSQL                  (enriched_anomalies, agent_investigations)
    - Neo4j                       (ForensicsAgent entity graph)
    - Qdrant                      (InvestigationAgent KNN search)
    - Kafka broker at 127.0.0.1:29092

Usage:
    python scripts/tests/test_integration_e2e.py
    python scripts/tests/test_integration_e2e.py --anomaly-id <uuid>   # pin a specific anomaly
    python scripts/tests/test_integration_e2e.py --timeout 30          # wait longer (default 15s)
    python scripts/tests/test_integration_e2e.py --api                 # also hit the REST endpoint

Exit codes:
    0 — investigation complete with at least one finding
    1 — investigation failed, timed out, or no row created
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import psycopg2
import psycopg2.extras
from kafka import KafkaProducer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:29092")
TOPIC = "dfp-agent-tasks"
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8001/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    from modules.utils.db import get_db_url

    return get_db_url()


def _pick_anomaly(conn: psycopg2.extensions.connection) -> dict:
    """Return a HIGH or CRITICAL anomaly that already has a risk_score."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT anomaly_id, user_id, anomaly_score, root_cause, severity, risk_score
            FROM   enriched_anomalies
            WHERE  is_anomaly = TRUE
              AND  severity IN ('HIGH', 'CRITICAL')
            ORDER  BY anomaly_score DESC
            LIMIT  1
        """)
        row = cur.fetchone()
    if row is None:
        sys.exit(
            "[ERROR] No HIGH/CRITICAL anomaly with risk_score found in DB. "
            "Run the AI orchestrator against some events first."
        )
    return dict(row)


def _poll_investigation(
    conn: psycopg2.extensions.connection,
    anomaly_id: str,
    timeout: int,
) -> dict | None:
    """
    Poll agent_investigations for the given anomaly_id until status is
    terminal (complete / failed) or timeout is reached.
    Returns the row dict or None on timeout.
    """
    deadline = time.monotonic() + timeout
    dot_interval = 2
    next_dot = time.monotonic() + dot_interval

    while time.monotonic() < deadline:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
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
                LEFT   JOIN agent_findings af
                         ON af.investigation_id = ai.investigation_id
                WHERE  ai.anomaly_id = %s
                GROUP  BY ai.investigation_id
                ORDER  BY ai.triggered_at DESC
                LIMIT  1
            """,
                (anomaly_id,),
            )
            row = cur.fetchone()
            conn.rollback()  # avoid idle-in-transaction

        if row and row["status"] in ("complete", "failed"):
            return dict(row)

        if time.monotonic() >= next_dot:
            print(".", end="", flush=True)
            next_dot += dot_interval

        time.sleep(1)

    print()  # newline after dots
    return None


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
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Orchestrator E2E integration test")
    parser.add_argument("--anomaly-id", help="Pin a specific anomaly UUID (default: auto-pick HIGH/CRITICAL)")
    parser.add_argument("--timeout", type=int, default=15, help="Seconds to wait for investigation (default: 15)")
    parser.add_argument("--api", action="store_true", help="Also validate the REST endpoint after DB check")
    args = parser.parse_args()

    db_url = _get_db_url()

    print("=" * 70)
    print("Agent Orchestrator — End-to-End Integration Test")
    print("=" * 70)

    # ── Connect to DB ────────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(db_url)
    except Exception as exc:
        sys.exit(f"[ERROR] Cannot connect to PostgreSQL: {exc}")

    # ── Pick anomaly ─────────────────────────────────────────────────────────
    if args.anomaly_id:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT anomaly_id, root_cause, severity, risk_score FROM enriched_anomalies WHERE anomaly_id = %s",
                (args.anomaly_id,),
            )
            row = cur.fetchone()
        if row is None:
            sys.exit(f"[ERROR] anomaly_id {args.anomaly_id!r} not found in enriched_anomalies")
        anomaly = dict(row)
    else:
        anomaly = _pick_anomaly(conn)

    anomaly_id = str(anomaly["anomaly_id"])
    severity_raw = anomaly.get("severity")

    if severity_raw is None:
        if args.anomaly_id:
            sys.exit(
                f"[ERROR] severity is NULL for anomaly_id {anomaly_id!r} in enriched_anomalies; "
                "please set a severity in the database or choose a different anomaly_id"
            )
        severity = "HIGH"
    else:
        severity = str(severity_raw).upper()

    risk_score = float(anomaly.get("risk_score") or 0.0)
    root_cause = str(anomaly.get("root_cause") or "Unknown")

    print("\nSelected anomaly:")
    print(f"  anomaly_id  : {anomaly_id}")
    print(f"  severity    : {severity}")
    print(f"  risk_score  : {risk_score:.1f}")
    print(f"  root_cause  : {root_cause}")

    # ── Publish task ─────────────────────────────────────────────────────────
    print(f"\nPublishing to {TOPIC} via {BOOTSTRAP} ...")
    try:
        producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        producer.send(
            TOPIC,
            value={
                "anomaly_id": anomaly_id,
                "severity": severity,
                "risk_score": risk_score,
                "root_cause": root_cause,
            },
            key=anomaly_id.encode(),
        )
        producer.flush(timeout=5)
        producer.close()
    except Exception as exc:
        sys.exit(f"[ERROR] Kafka publish failed: {exc}")

    print(f"Task published — polling DB for up to {args.timeout}s ", end="", flush=True)

    # ── Poll DB ──────────────────────────────────────────────────────────────
    result = _poll_investigation(conn, anomaly_id, args.timeout)
    conn.close()

    if result is None:
        print(f"\nTIMEOUT — no terminal investigation row after {args.timeout}s.")
        print("   Is run_agent_orchestrator.py running and consuming dfp-agent-tasks?")
        sys.exit(1)

    # ── Report ───────────────────────────────────────────────────────────────
    status = result["status"]
    findings = result["findings"] or []
    confidence = result["confidence_score"]
    agents = result["agents_invoked"]

    print(f"\n{'PASS' if status == 'complete' else 'FAIL'} Investigation {status.upper()}")
    print(f"  investigation_id : {result['investigation_id']}")
    print(f"  agents_invoked   : {agents}")
    print(f"  confidence_score : {confidence}")
    print(f"  findings         : {len(findings)}")

    for f in findings:
        icon = "PASS" if f.get("status") == "complete" else "FAIL"
        print(
            f"    {icon} {f.get('agent_type'):<20} status={f.get('status'):<10} "
            f"confidence={f.get('confidence') or '—':<6} latency={f.get('latency_ms') or '—'}ms"
        )

    if args.api:
        _check_api(anomaly_id)

    print()
    if status != "complete":
        print("TEST FAILED — investigation did not complete successfully.")
        sys.exit(1)
    if not findings:
        print("TEST FAILED — no agent findings recorded.")
        sys.exit(1)

    print("TEST PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
