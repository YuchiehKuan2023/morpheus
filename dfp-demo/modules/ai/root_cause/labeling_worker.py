#!/usr/bin/env python3
"""
Root Cause Labeling Worker — Stage 2 periodic inference job

Classifies TRUE anomalies (is_anomaly=TRUE) that have not yet been classified
(classified_at IS NULL) by running the trained DistilBERT root cause classifier
and writing the results back to enriched_anomalies via PersistenceService.

Workflow
--------
    1. Load trained model from data/models/root_cause/ (or --model-dir)
    2. Query enriched_anomalies for unclassified TRUE anomalies
    3. Run clf.predict_batch() in configurable batch_size chunks
    4. Derive severity from anomaly_score thresholds
    5. Write root_cause, sub_category, confidence, reasoning, severity via
       PersistenceService.update_classification()
    6. Log a summary (n_classified, confidence distribution, per-class counts)

Severity mapping  (anomaly_score → severity label)
---------------------------------------------------
    > 5.0         →  CRITICAL
    >= 3.0 – 5.0  →  HIGH
    >= 2.5 – 3.0  →  MEDIUM
    > 2.0 – 2.5   →  LOW

Canonical source: scripts/utils/extract_severity.py :: severity_from_score()
This mapping is deterministic and explicit so the SOC team can audit it.  It
deliberately does NOT depend on the prediction confidence (confidence measures
how certain the model is about the *category*, not the *risk level*).

Usage
-----
    # Classify up to 100 unclassified TRUE anomalies
    python -m modules.ai.root_cause.labeling_worker --limit 100

    # Dry run — show what would be classified without writing to DB
    python -m modules.ai.root_cause.labeling_worker --dry-run

    # Show DB statistics and exit
    python -m modules.ai.root_cause.labeling_worker --stats

    # Re-classify records already classified (force refresh)
    python -m modules.ai.root_cause.labeling_worker --reclassify --limit 50

    # Custom model directory and database
    python -m modules.ai.root_cause.labeling_worker \\
        --model-dir /data/models/root_cause_v2 \\
        --limit 500

Reference
---------
    modules/ai/root_cause/classifier.py   (DistilBERT model, predict_batch)
    modules/ai/root_cause/training.py     (fine-tuning loop)
    modules/ai/enrichment/persistence_service.py  (update_classification)
    docs/implementation/PROGRESS_TRACKER.md  (Week 11-14: Stage 2)

Author: AI Intelligence Layer Team
Date: 2026-03-03
"""

from __future__ import annotations

import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Sibling-module imports
# ---------------------------------------------------------------------------
sys.path.append(str(Path(__file__).parents[3]))

from modules.ai.enrichment.persistence_service import PersistenceService  # noqa: E402
from modules.ai.risk_scoring.risk_scorer import (  # noqa: E402
    DEFAULT_MODEL_DIR as RISK_MODEL_DIR,
)
from modules.ai.risk_scoring.risk_scorer import (
    RiskScorer,
)
from modules.ai.root_cause.classifier import (  # noqa: E402
    DEFAULT_MODEL_DIR,
    ROOT_CAUSE_MAP,
    ClassificationResult,
    RootCauseClassifier,
)
from modules.utils.db import get_db_params  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB connection defaults
# ---------------------------------------------------------------------------
DB_CONFIG: dict[str, Any] = get_db_params()

# ---------------------------------------------------------------------------
# Severity mapping (anomaly_score thresholds) — canonical scale, see scripts/utils/extract_severity.py
# ---------------------------------------------------------------------------
#   score > 5.0           → CRITICAL
#   score >= 3.0 – 5.0    → HIGH
#   score >= 2.5 – 3.0    → MEDIUM
#   score > 2.0 – 2.5     → LOW
# Detection threshold is 2.0 — scores below that are never stored.
from scripts.utils import severity_from_score as anomaly_score_to_severity  # noqa: E402

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def fetch_unclassified(
    limit: int,
    reclassify: bool = False,
) -> list[dict[str, Any]]:
    """
    Fetch above-threshold anomaly records pending Stage 2 classification.

    Classifies ALL detections that passed the DFP threshold (i.e. have an
    enriched_anomalies row), regardless of the Stage 1 is_anomaly verdict.
    Human analysts need root cause, risk score, and SHAP even for events
    labelled as false positive or uncertain.

    Args:
        limit:       Maximum number of records to return.
        reclassify:  If True, include already-classified records too
                     (for force-refresh runs).

    Returns:
        List of dicts with keys: anomaly_id, top_features, anomaly_score.
    """
    where_clause = "TRUE" if reclassify else "classified_at IS NULL"
    query = f"""
        SELECT
            anomaly_id::text,
            COALESCE(raw_detection->>'top_features', '') AS top_features,
            anomaly_score
        FROM enriched_anomalies
        WHERE {where_clause}
        ORDER BY anomaly_score DESC
        LIMIT %s
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def fetch_full_rows(anomaly_ids: list[str]) -> list[dict[str, Any]]:
    """
    Fetch full enriched_anomalies rows for a list of anomaly_ids.

    Used by the risk scorer which needs original_event, ai_enrichment,
    sub_category, severity etc. — columns not returned by fetch_unclassified().
    """
    if not anomaly_ids:
        return []
    query = """
        SELECT
            anomaly_id::text,
            anomaly_score,
            mean_abs_z,
            sub_category,
            severity,
            classification_confidence,
            validation_confidence,
            original_event,
            raw_detection,
            ai_enrichment
        FROM enriched_anomalies
        WHERE anomaly_id = ANY(%s::uuid[])
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (anomaly_ids,))
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return rows


def fetch_stats() -> dict[str, Any]:
    """
    Return a statistics snapshot of the enriched_anomalies classification state.

    Returns:
        Dict with counts for total, true anomalies, classified, unclassified,
        and per-root_cause and per-sub_category breakdowns.
    """
    query = """
        SELECT
            COUNT(*)                                           AS total,
            COUNT(*) FILTER (WHERE is_anomaly = TRUE)         AS true_anomalies,
            COUNT(*) FILTER (WHERE is_anomaly = FALSE)        AS false_positives,
            COUNT(*) FILTER (WHERE is_anomaly IS NULL)        AS unlabeled,
            COUNT(*) FILTER (WHERE classified_at IS NOT NULL) AS classified,
            COUNT(*) FILTER (
                WHERE is_anomaly = TRUE AND classified_at IS NULL
            )                                                  AS unclassified_true,
            AVG(
                classification_confidence
            ) FILTER (WHERE classified_at IS NOT NULL)         AS avg_confidence
        FROM enriched_anomalies
    """
    root_cause_query = """
        SELECT root_cause, COUNT(*) AS n
        FROM enriched_anomalies
        WHERE root_cause IS NOT NULL
        GROUP BY root_cause
        ORDER BY n DESC
    """
    sub_cat_query = """
        SELECT sub_category, COUNT(*) AS n,
               AVG(classification_confidence) AS avg_conf
        FROM enriched_anomalies
        WHERE sub_category IS NOT NULL
          AND classified_at IS NOT NULL
        GROUP BY sub_category
        ORDER BY n DESC
    """

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            summary = dict(cur.fetchone() or {})  # type: ignore[arg-type]
            cur.execute(root_cause_query)
            root_causes = [dict(r) for r in cur.fetchall()]
            cur.execute(sub_cat_query)
            sub_cats = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    return {
        "summary": summary,
        "by_root_cause": root_causes,
        "by_sub_category": sub_cats,
    }


# ---------------------------------------------------------------------------
# Dominant-feature override
# ---------------------------------------------------------------------------

# Feature name fragments → sub_category override when one feature dominates
_FEATURE_TO_SUB_CATEGORY: list[tuple[str, str]] = [
    ("operatingsystem", "Unusual Operating System"),
    ("browser", "Unusual Browser"),
    ("displayname", "Unknown Device"),
    ("location", "Unusual Location"),
    ("country", "Unusual Location"),
    ("travel_speed", "Impossible Travel"),
    ("appdisplayname", "Unusual Application"),
]

# Factor by which the top z-score must exceed the second highest to be considered dominant
_DOMINANCE_RATIO = 3.0

# Matches the inference pipeline format: 'feature=value (z=X.XX)'
# Identical to FeatureBridge.FEATURE_PATTERN — kept local to avoid a circular import.
_TOP_FEATURES_PATTERN = re.compile(r"(\w+)=([^(]+)\s*\(z=([\d.]+)\)")


def _dominant_feature_override(
    sub_category: str,
    top_features_str: str,
) -> str:
    """
    If DistilBERT predicted a catch-all sub_category (Multi-Factor Anomaly or
    Broad Deviation) AND one feature's z-score is ≥ DOMINANCE_RATIO × the
    second feature's z-score, the detection is effectively single-feature-driven.
    In that case override sub_category with the specific class for that feature.

    top_features_str format:  "feature=value (z=X.XX), feature2=value2 (z=Y.YY), ..."
    Example: "deviceDetailoperatingSystem=ChromeOS 120 (z=19.98), appDisplayName=Adobe (z=1.12)"
    """
    if sub_category not in ("Multi-Factor Anomaly", "Broad Deviation"):
        return sub_category

    # Parse z-scores using the canonical inference-pipeline format: 'feature=value (z=X.XX)'
    zscores: list[tuple[str, float]] = [
        (m.group(1).lower(), float(m.group(3))) for m in _TOP_FEATURES_PATTERN.finditer(top_features_str)
    ]

    if len(zscores) < 2:
        return sub_category

    # Sort descending by z-score
    zscores.sort(key=lambda x: x[1], reverse=True)
    top_name, top_z = zscores[0]
    _, second_z = zscores[1]

    if second_z == 0 or (top_z / second_z) < _DOMINANCE_RATIO:
        return sub_category  # Not clearly dominated by one feature

    # Find the matching sub_category for the dominant feature
    for fragment, mapped_sub_category in _FEATURE_TO_SUB_CATEGORY:
        if fragment in top_name:
            logger.debug(
                "Dominant-feature override: %s → %s (top_z=%.2f, second_z=%.2f, ratio=%.1f)",
                sub_category,
                mapped_sub_category,
                top_z,
                second_z,
                top_z / second_z,
            )
            return mapped_sub_category

    return sub_category


# ---------------------------------------------------------------------------
# Write results back to DB
# ---------------------------------------------------------------------------


def write_classifications(
    results: list[ClassificationResult],
    records: list[dict[str, Any]],
    persistence: PersistenceService,
) -> tuple[int, int]:
    """
    Persist a batch of ClassificationResult objects via PersistenceService.

    Args:
        results:     Predictions from clf.predict_batch().
        records:     Original DB rows (same order), used for anomaly_score.
        persistence: Initialised PersistenceService (Postgres connection open).

    Returns:
        (n_success, n_failed) counts.
    """
    score_by_id = {r["anomaly_id"]: float(r["anomaly_score"]) for r in records}
    features_by_id = {r["anomaly_id"]: str(r.get("top_features", "")) for r in records}

    n_success = 0
    n_failed = 0

    for result in results:
        anomaly_score = score_by_id.get(result.anomaly_id, 0.0)
        severity = anomaly_score_to_severity(anomaly_score)

        # Apply dominant-feature override for catch-all sub_categories before writing.
        top_features_str = features_by_id.get(result.anomaly_id, "")
        effective_sub_category = _dominant_feature_override(result.sub_category, top_features_str)
        effective_root_cause = ROOT_CAUSE_MAP.get(effective_sub_category, result.root_cause)
        if effective_sub_category != result.sub_category:
            logger.info(
                "Dominant-feature override applied for %s: %s/%s → %s/%s",
                result.anomaly_id,
                result.sub_category,
                result.root_cause,
                effective_sub_category,
                effective_root_cause,
            )

        ok = persistence.update_classification(
            anomaly_id=result.anomaly_id,
            root_cause=effective_root_cause,
            severity=severity,
            sub_category=effective_sub_category,
            confidence=result.confidence,
            reasoning=result.reasoning,
            classified_by="distilbert",
        )

        if ok:
            n_success += 1
        else:
            n_failed += 1
            logger.warning(f"update_classification returned False for {result.anomaly_id}")

    return n_success, n_failed


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(
    limit: int = 100,
    batch_size: int = 32,
    model_dir: str | Path = DEFAULT_MODEL_DIR,
    reclassify: bool = False,
    dry_run: bool = False,
    risk_model_dir: str | Path = RISK_MODEL_DIR,
) -> dict[str, Any]:
    """
    Classify unclassified TRUE anomalies and write results to DB.

    After writing root-cause classifications, also runs the risk scorer
    (if its model exists) and writes risk_score + risk_factors back to
    the same rows.  If the risk model has not been trained yet, this step
    is silently skipped so the worker remains fully operational.

    Args:
        limit:          Maximum records to classify in this run.
        batch_size:     Inference batch size (reduce on low-memory machines).
        model_dir:      Path to trained DistilBERT model directory.
        reclassify:     If True, re-classify already-classified records too.
        dry_run:        Run inference but do NOT write to DB.
        risk_model_dir: Path to trained XGBoost risk scorer directory.

    Returns:
        Summary dict with n_fetched, n_classified, n_failed, elapsed_seconds,
        confidence stats, per-root_cause / per-sub_category counts, and
        risk_scored (int) count.
    """
    run_start = datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # 1. Load model
    # ------------------------------------------------------------------
    logger.info(f"Loading RootCauseClassifier from {model_dir}")
    clf = RootCauseClassifier(model_dir=model_dir)
    clf.load()
    logger.info("Model loaded successfully.")

    # ------------------------------------------------------------------
    # 2. Fetch records
    # ------------------------------------------------------------------
    logger.info(f"Fetching up to {limit} {'all' if reclassify else 'unclassified'} TRUE anomalies…")
    records = fetch_unclassified(limit=limit, reclassify=reclassify)

    if not records:
        logger.info("No records to classify.")
        return {
            "n_fetched": 0,
            "n_classified": 0,
            "n_failed": 0,
            "elapsed_seconds": 0.0,
            "message": "Nothing to classify.",
        }

    logger.info(f"Fetched {len(records)} records.")

    # ------------------------------------------------------------------
    # 3. Run inference
    # ------------------------------------------------------------------
    logger.info(f"Running inference (batch_size={batch_size})…")
    results = clf.predict_batch(records, batch_size=batch_size)

    # ------------------------------------------------------------------
    # 4. Write to DB (unless dry_run)
    # ------------------------------------------------------------------
    n_success = 0
    n_failed = 0

    if dry_run:
        logger.info("[DRY RUN] Skipping DB writes.")
    else:
        # batch_mode=True skips Neo4j/Qdrant updates (not needed for classification writes)
        with PersistenceService(batch_mode=True, enable_kafka=False) as persistence:
            n_success, n_failed = write_classifications(results, records, persistence)

        logger.info(f"Wrote {n_success} classifications ({n_failed} failed).")

    # ------------------------------------------------------------------
    # 5. Risk scoring (runs immediately after classification, same records)
    # ------------------------------------------------------------------
    n_risk_scored = 0
    if not dry_run and n_success > 0:
        risk_model_path = Path(risk_model_dir) / "xgboost_risk_scorer.json"
        if risk_model_path.exists():
            try:
                logger.info("Loading RiskScorer…")
                scorer = RiskScorer(model_dir=risk_model_dir)
                scorer.load()

                # Fetch full rows — the classification worker only fetched 3 columns
                scored_ids = [r.anomaly_id for r in results]
                full_rows = fetch_full_rows(scored_ids)
                id_to_row = {r["anomaly_id"]: r for r in full_rows}

                with PersistenceService(batch_mode=True, enable_kafka=False) as persistence:
                    for result in results:
                        row = id_to_row.get(result.anomaly_id)
                        if row is None:
                            continue
                        try:
                            risk_score, risk_factors = scorer.predict(row)
                            anomaly_score = float(row.get("anomaly_score") or 0.0)
                            persistence.update_classification(
                                anomaly_id=result.anomaly_id,
                                root_cause=result.root_cause,
                                severity=anomaly_score_to_severity(anomaly_score),
                                sub_category=result.sub_category,
                                confidence=result.confidence,
                                reasoning=result.reasoning,
                                classified_by="distilbert",
                                risk_score=risk_score,
                                risk_factors=risk_factors,
                            )
                            n_risk_scored += 1
                        except Exception as exc:
                            logger.warning(f"Risk scoring failed for {result.anomaly_id}: {exc}")

                logger.info(f"Risk scored {n_risk_scored}/{n_success} records.")
            except Exception as exc:
                logger.warning(f"Risk scorer unavailable: {exc}")
        else:
            logger.info(
                "Risk scorer model not found — skipping. Run: python -m modules.ai.risk_scoring.risk_scorer_training"
            )

    # ------------------------------------------------------------------
    # 6. Build summary
    # ------------------------------------------------------------------
    elapsed = (datetime.now(tz=timezone.utc) - run_start).total_seconds()
    confidences = [r.confidence for r in results]
    root_cause_counts = dict(Counter(r.root_cause for r in results))
    sub_category_counts = dict(Counter(r.sub_category for r in results))

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    high_conf = sum(1 for c in confidences if c >= 0.80)
    mid_conf = sum(1 for c in confidences if 0.60 <= c < 0.80)
    low_conf = sum(1 for c in confidences if c < 0.60)

    summary = {
        "n_fetched": len(records),
        "n_classified": n_success if not dry_run else len(results),
        "n_failed": n_failed,
        "n_risk_scored": n_risk_scored,
        "dry_run": dry_run,
        "elapsed_seconds": round(elapsed, 2),
        "confidence": {
            "avg": round(avg_conf, 4),
            "high_80_plus": high_conf,
            "mid_60_80": mid_conf,
            "low_below_60": low_conf,
        },
        "by_root_cause": root_cause_counts,
        "by_sub_category": sub_category_counts,
    }

    return summary


# ---------------------------------------------------------------------------
# Module-level singletons — loaded once, reused across classify_single() calls
# ---------------------------------------------------------------------------

_singleton_clf: RootCauseClassifier | None = None
_singleton_clf_model_dir: str | None = None

_singleton_scorer: RiskScorer | None = None
_singleton_scorer_model_dir: str | None = None


def _get_classifier(model_dir: str | Path) -> RootCauseClassifier:
    """Return a cached RootCauseClassifier, loading from disk only if needed."""
    global _singleton_clf, _singleton_clf_model_dir
    key = str(model_dir)
    if _singleton_clf is None or _singleton_clf_model_dir != key:
        logger.info("Loading RootCauseClassifier singleton from %s", key)
        clf = RootCauseClassifier(model_dir=model_dir)
        clf.load()
        _singleton_clf = clf
        _singleton_clf_model_dir = key
    return _singleton_clf


def _get_risk_scorer(risk_model_dir: str | Path) -> RiskScorer | None:
    """Return a cached RiskScorer, or None if the model file does not exist."""
    global _singleton_scorer, _singleton_scorer_model_dir
    risk_model_path = Path(risk_model_dir) / "xgboost_risk_scorer.json"
    if not risk_model_path.exists():
        return None
    key = str(risk_model_dir)
    if _singleton_scorer is None or _singleton_scorer_model_dir != key:
        logger.info("Loading RiskScorer singleton from %s", key)
        scorer = RiskScorer(model_dir=risk_model_dir)
        scorer.load()
        _singleton_scorer = scorer
        _singleton_scorer_model_dir = key
    return _singleton_scorer


# ---------------------------------------------------------------------------
# Single-record helper (used by AI Orchestrator)
# ---------------------------------------------------------------------------


def classify_single(
    anomaly_id: str,
    model_dir: str | Path = DEFAULT_MODEL_DIR,
    risk_model_dir: str | Path = RISK_MODEL_DIR,
) -> dict[str, Any] | None:
    """Classify a single TRUE anomaly by anomaly_id and write result to DB.

    Designed for real-time use by the AI Orchestrator immediately after a new
    anomaly is persisted to enriched_anomalies.  Uses module-level singletons
    so the DistilBERT and RiskScorer models are loaded from disk only once.

    Args:
        anomaly_id:     UUID of the enriched_anomaly row to classify.
        model_dir:      Path to the trained DistilBERT model directory.
        risk_model_dir: Path to the trained XGBoost risk scorer directory.

    Returns:
        Summary dict with ``anomaly_id``, ``root_cause``, ``sub_category``,
        ``confidence``, ``n_classified``, ``n_failed``, ``n_risk_scored``,
        or ``None`` if the anomaly_id does not exist in the DB.
    """
    # 1. Fetch single record in the 3-column format expected by predict_batch.
    query = """
        SELECT
            anomaly_id::text,
            COALESCE(raw_detection->>'top_features', '') AS top_features,
            anomaly_score
        FROM enriched_anomalies
        WHERE anomaly_id = %s
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (anomaly_id,))
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        logger.warning(f"classify_single: anomaly_id={anomaly_id!r} not found in enriched_anomalies")
        return None

    records = [dict(row)]

    # 2. Load classifier and run inference (singleton — loaded only once).
    clf = _get_classifier(model_dir)
    results = clf.predict_batch(records, batch_size=1)

    # 3. Write classification to DB.
    with PersistenceService(batch_mode=True, enable_kafka=False) as persistence:
        n_success, n_failed = write_classifications(results, records, persistence)

    if n_success == 0:
        logger.warning(f"classify_single: write_classifications failed for {anomaly_id}")
        return {"anomaly_id": anomaly_id, "n_classified": 0, "n_failed": 1, "n_risk_scored": 0}

    # 4. Risk scoring (skipped silently if model not yet trained).
    n_risk_scored = 0
    scorer = _get_risk_scorer(risk_model_dir)
    if scorer is not None:
        try:
            full_rows = fetch_full_rows([anomaly_id])
            if full_rows:
                row_data = full_rows[0]
                result_obj = results[0]
                risk_score, risk_factors = scorer.predict(row_data)
                anomaly_score_val = float(row_data.get("anomaly_score") or 0.0)
                with PersistenceService(batch_mode=True, enable_kafka=False) as persistence:
                    persistence.update_classification(
                        anomaly_id=anomaly_id,
                        root_cause=result_obj.root_cause,
                        severity=anomaly_score_to_severity(anomaly_score_val),
                        sub_category=result_obj.sub_category,
                        confidence=result_obj.confidence,
                        reasoning=result_obj.reasoning,
                        classified_by="distilbert",
                        risk_score=risk_score,
                        risk_factors=risk_factors,
                    )
                n_risk_scored = 1
        except Exception as exc:
            logger.warning(f"classify_single: risk scoring failed for {anomaly_id}: {exc}")

    result_obj = results[0]
    logger.info(
        f"classify_single: {anomaly_id} → {result_obj.root_cause}/{result_obj.sub_category} "
        f"(conf={result_obj.confidence:.2f}, risk_scored={bool(n_risk_scored)})"
    )
    return {
        "anomaly_id": anomaly_id,
        "root_cause": result_obj.root_cause,
        "sub_category": result_obj.sub_category,
        "confidence": result_obj.confidence,
        "n_classified": n_success,
        "n_failed": n_failed,
        "n_risk_scored": n_risk_scored,
    }


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------


def print_run_summary(summary: dict[str, Any]) -> None:
    """Print a human-readable summary of a classification run."""
    print(f"\n{'=' * 60}")
    print("Stage 2 Labeling Worker — Run Summary")
    print(f"{'=' * 60}")
    print(f"  Records fetched     : {summary['n_fetched']}")
    if summary.get("dry_run"):
        print("  (DRY RUN — no DB writes)")
    else:
        print(f"  Written to DB       : {summary['n_classified']}")
        print(f"  Failed              : {summary['n_failed']}")
        print(f"  Risk scored         : {summary.get('n_risk_scored', 0)}")
    print(f"  Elapsed             : {summary['elapsed_seconds']}s")

    conf = summary.get("confidence", {})
    if conf:
        print("\n  Confidence distribution:")
        print(f"    avg         : {conf.get('avg', 0):.4f}")
        print(f"    ≥ 0.80      : {conf.get('high_80_plus', 0)}")
        print(f"    0.60–0.79   : {conf.get('mid_60_80', 0)}")
        print(f"    < 0.60      : {conf.get('low_below_60', 0)}")

    rc = summary.get("by_root_cause", {})
    if rc:
        print("\n  By root cause:")
        for cause, n in sorted(rc.items(), key=lambda x: x[1], reverse=True):
            print(f"    {cause:<35} {n}")

    sc = summary.get("by_sub_category", {})
    if sc:
        print("\n  By sub category:")
        for cat, n in sorted(sc.items(), key=lambda x: x[1], reverse=True):
            print(f"    {cat:<35} {n}")

    print()


def print_stats(stats: dict[str, Any]) -> None:
    """Print DB classification statistics."""
    s = stats.get("summary", {})
    print(f"\n{'=' * 60}")
    print("enriched_anomalies — Classification State")
    print(f"{'=' * 60}")
    print(f"  Total records         : {s.get('total', 0)}")
    print(f"  TRUE anomalies        : {s.get('true_anomalies', 0)}")
    print(f"  False positives       : {s.get('false_positives', 0)}")
    print(f"  Unlabeled (Stage 1)   : {s.get('unlabeled', 0)}")
    print(f"  Classified (Stage 2)  : {s.get('classified', 0)}")
    print(f"  Unclassified (TRUE)   : {s.get('unclassified_true', 0)}")
    avg_conf = s.get("avg_confidence")
    if avg_conf is not None:
        print(f"  Avg model confidence  : {float(avg_conf):.4f}")

    rc = stats.get("by_root_cause", [])
    if rc:
        print("\n  By root cause:")
        for row in rc:
            print(f"    {row['root_cause']:<35} {row['n']}")

    sc = stats.get("by_sub_category", [])
    if sc:
        print("\n  By sub category (classified records only):")
        for row in sc:
            avg = float(row["avg_conf"]) if row["avg_conf"] is not None else 0.0
            print(f"    {row['sub_category']:<35} {row['n']:>4}  avg_conf={avg:.3f}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parents[3] / ".env", override=False)
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Stage 2 Root Cause Labeling Worker — classifies TRUE anomalies in enriched_anomalies",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to classify per run",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Inference batch size (reduce on low-memory machines)",
    )
    parser.add_argument(
        "--model-dir",
        default=str(DEFAULT_MODEL_DIR),
        help="Trained model directory (contains model_state.pt and config.json)",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Re-classify already-classified records (force refresh)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run inference but do NOT write results to DB",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print DB classification statistics and exit",
    )
    parser.add_argument(
        "--risk-model-dir",
        default=str(RISK_MODEL_DIR),
        help="Trained XGBoost risk scorer directory (skipped if model not found)",
    )
    args = parser.parse_args()

    if args.stats:
        print_stats(fetch_stats())
        sys.exit(0)

    summary = run(
        limit=args.limit,
        batch_size=args.batch_size,
        model_dir=args.model_dir,
        reclassify=args.reclassify,
        dry_run=args.dry_run,
        risk_model_dir=args.risk_model_dir,
    )
    print_run_summary(summary)

    # Exit code 1 if any DB writes failed
    sys.exit(1 if summary.get("n_failed", 0) > 0 else 0)
