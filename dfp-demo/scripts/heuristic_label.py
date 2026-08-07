#!/usr/bin/env python3
"""
Heuristic Score-Based Labeling Script

Labels enriched_anomalies rows WITHOUT calling the LLM API, using DFP
anomaly score thresholds aligned to the real DFP scoring model:

    score >  5.0 → TRUE_POSITIVE   (CRITICAL: impossible travel, mass deviation)
    score >= 2.5 → TRUE_POSITIVE   (MEDIUM/HIGH: real anomaly above detection threshold)
    score <  2.5 → FALSE_POSITIVE  (very mild deviation — consistent with benign activity)

Rationale:
    DFP anomaly scores are Z-score aggregates.  Anything above 2.5 represents a
    statistically meaningful deviation from the user's behavioural model and should
    be treated as a genuine detection.  Single-feature anomalies (device, location, OS)
    typically land in the 2.5-4.0 range; multi-factor events score 4-8; impossible
    travel is always > 8.  The old thresholds (FP<3, TP>=10) incorrectly discarded
    seven of the nine sub_category classes.  Updated 2026-03-09.

    Severity bands:
        < 2.0              : below detection threshold (not stored)
        2.0 - 2.5          : LOW    (FP)
        2.5 - 3.0          : MEDIUM (TP, low confidence)
        3.0 - 5.0          : HIGH   (TP, reliable single/double-feature detection)
        > 5.0              : CRITICAL (TP, multi-factor or impossible travel)

Columns updated per detection (enriched_anomalies schema):
    Stage 1 (validation):
        is_anomaly, validation_confidence, validation_reasoning,
        validated_at, validated_by, dfp_retrain_status,
        feedback_to_dfp (TRUE for FP only), status, severity, updated_at
    Stage 2 (classification) — heuristic bootstrap for TRUE POSITIVES only:
        root_cause, sub_category, classification_confidence,
        classification_reasoning, classified_at
        Derived from raw_detection->>'top_features' feature string.
        Will be overwritten by the real classifier.py (DistilBERT) once trained.
    Risk:
        risk_score, risk_factors → LEFT NULL (populated by Stage 2)

Usage:
    # Preview what will be labeled (no writes)
    python scripts/heuristic_label.py --dry-run

    # Apply labels
    python scripts/heuristic_label.py

    # Apply labels then show final stats
    python scripts/heuristic_label.py --stats

Safe to run multiple times — skips already-labeled rows by default.
Use --relabel to overwrite existing labels (not recommended in production).
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[1] / ".env", override=False)
except ImportError:
    pass

import psycopg2
import psycopg2.extras

from modules.utils.db import get_db_params
from scripts.utils import severity_from_score as _severity

# ── Config ────────────────────────────────────────────────────────────────────
DB_CONFIG = get_db_params()

TP_THRESHOLD = 2.5  # score >= this → TRUE_POSITIVE  (anything above 2.5 is a real anomaly)
FP_THRESHOLD = 2.5  # score <  this → FALSE_POSITIVE (below detection threshold)
CONFIDENCE = 0.90
VALIDATED_BY = "heuristic_score"
REASONING_TP = (
    "Heuristic label: anomaly_score = {score:.2f} (threshold {thresh}). "
    "Score in {sev} range — statistically extreme deviation from user baseline."
)
REASONING_FP = (
    "Heuristic label: anomaly_score = {score:.2f} (threshold < {thresh}). "
    "Score below detection threshold — consistent with benign activity (no real deviation)."
)


def _root_cause_from_features(top_features: str) -> tuple[str, str, str]:
    """
    Heuristic root cause from raw_detection top_features string.

    Returns (root_cause, sub_category, reasoning).
    Priority order matters — impossible travel must beat plain location.
    Will be overwritten by root_cause/classifier.py once the DistilBERT
    model is trained on LLM-validated labels.
    """
    f = (top_features or "").lower()

    if "travel_speed_kmph" in f:
        return (
            "Geographic Anomaly",
            "Impossible Travel",
            "Impossible travel speed detected — login from geographically implausible location given prior session.",
        )
    # Multi-category: requires app + at least one of (device, location) → strong takeover signal
    # device+location without app is still a geographic/device issue, not a full takeover
    has_app = "appdisplayname" in f
    has_device = "devicedetail" in f
    has_location = "locationcity" in f or "locationcountry" in f
    if has_app and (has_device or has_location):
        return (
            "Account Takeover",
            "Multi-Factor Anomaly",
            "Simultaneous anomalies across multiple feature categories (app, device, location) — broad deviation from baseline.",
        )
    if has_device and has_location:
        return (
            "Geographic Anomaly",
            "Location with Unusual Device",
            "Login from unusual location combined with unrecognised device attributes.",
        )
    if "unknown-laptop" in f or ("devicedetaildisplayname" in f and "unknown" in f):
        return (
            "Unmanaged Device",
            "Unknown Device",
            "Access from unrecognised or unmanaged device not in user baseline.",
        )
    if has_app:
        return (
            "Unauthorized Application Access",
            "Unusual Application",
            "Access to application outside user's typical usage pattern.",
        )
    if has_location:
        return (
            "Geographic Anomaly",
            "Unusual Location",
            "Login from geographic location outside user's established baseline.",
        )
    if "devicedetailbrowser" in f:
        return (
            "Browser Anomaly",
            "Unusual Browser",
            "Access from browser not present in user's baseline profile.",
        )
    if "devicedetailoperatingsystem" in f:
        return (
            "OS Anomaly",
            "Unusual Operating System",
            "Access from operating system not in user baseline.",
        )
    # Fallback — high score, unrecognised feature pattern
    return (
        "Account Takeover",
        "Broad Deviation",
        "Multiple feature categories deviate simultaneously from user baseline.",
    )


def apply_ambiguous_labels(conn, relabel: bool):
    """
    Label the MEDIUM-confidence band (2.5 - 5.0) with low-confidence heuristic labels.

    Updated 2026-03-09: With the new thresholds (FP < 2.5, TP >= 2.5) there is no
    true "ambiguous" band — everything >= 2.5 IS a TP.  This function is retained
    for backwards compatibility and to handle records that were ingested before the
    threshold change.  It now labels ALL records in the 2.5-5.0 band as TP at lower
    confidence (0.65) since they are genuine detections, just at moderate severity.

    The old split (5-10 → TP, 3-5 → FP) was INCORRECT and is removed.
    Records below 2.5 remain untouched here and are treated as FP by the primary
    heuristic pass (apply_labels).
    """
    MIDBAND_BY = "heuristic_midband"
    MIDBAND_CONF = 0.65  # Higher than old 0.55 — these are genuine TPs
    MIDBAND_SPLIT = 5.0  # Kept for SQL readability (upper/lower sub-bands of TP)

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    now = datetime.now(timezone.utc)
    where_extra = "" if relabel else "AND is_anomaly IS NULL"

    # ── Upper half (5.0+): high-confidence TP — already handled by apply_labels ──
    # apply_labels covers score >= TP_THRESHOLD (2.5).  This sub-band is just for
    # records that arrive here without being caught by the primary pass.
    cur.execute(
        f"""
        SELECT anomaly_id, anomaly_score,
               raw_detection->>'top_features' AS top_features
        FROM enriched_anomalies
        WHERE anomaly_score >= %s AND anomaly_score < %s {where_extra}
        ORDER BY anomaly_score DESC
    """,
        (MIDBAND_SPLIT, 99999.0),  # 5.0+ that slipped through
    )
    upper_rows = cur.fetchall()
    upper_count = 0
    for row in upper_rows:
        score = float(row["anomaly_score"])
        sev = _severity(score)
        val_reasoning = (
            f"Heuristic midband: anomaly_score={score:.2f} (score >= 5.0 band). "
            "Confirmed TP at lower confidence — pending LLM validation."
        )
        root_cause, sub_category, cls_reasoning = _root_cause_from_features(row["top_features"] or "")
        cur.execute(
            """
            UPDATE enriched_anomalies
            SET
                is_anomaly                 = TRUE,
                validation_confidence      = %s,
                validation_reasoning       = %s,
                validated_at               = %s,
                validated_by               = %s,
                dfp_retrain_status         = 'excluded',
                feedback_to_dfp            = FALSE,
                severity                   = %s,
                status                     = 'new',
                updated_at                 = NOW(),
                root_cause                 = %s,
                sub_category               = %s,
                classification_confidence  = %s,
                classification_reasoning   = %s,
                classified_at              = %s
            WHERE anomaly_id = %s
        """,
            (
                MIDBAND_CONF,
                val_reasoning,
                now,
                MIDBAND_BY,
                sev,
                root_cause,
                sub_category,
                MIDBAND_CONF,
                cls_reasoning,
                now,
                row["anomaly_id"],
            ),
        )
        upper_count += 1
    conn.commit()
    print(f"Labeled {upper_count} midband-upper rows as TRUE_POSITIVE (confidence 0.65)")

    # ── Lower half (2.5 – 5.0): MEDIUM TP ────────────────────────────────────
    # These are all genuine TPs (score >= 2.5).  Full TP treatment with lower conf.
    cur.execute(
        f"""
        SELECT anomaly_id, anomaly_score,
               raw_detection->>'top_features' AS top_features
        FROM enriched_anomalies
        WHERE anomaly_score >= %s AND anomaly_score < %s {where_extra}
        ORDER BY anomaly_score ASC
    """,
        (FP_THRESHOLD, MIDBAND_SPLIT),
    )
    lower_rows = cur.fetchall()
    lower_count = 0
    for row in lower_rows:
        score = float(row["anomaly_score"])
        sev = _severity(score)
        reasoning = (
            f"Heuristic midband: anomaly_score={score:.2f} (2.5-5.0 MEDIUM band). "
            "Score above detection threshold — treated as TP at moderate confidence."
        )
        root_cause, sub_category, cls_reasoning = _root_cause_from_features(row["top_features"] or "")
        cur.execute(
            """
            UPDATE enriched_anomalies
            SET
                is_anomaly                 = TRUE,
                validation_confidence      = %s,
                validation_reasoning       = %s,
                validated_at               = %s,
                validated_by               = %s,
                dfp_retrain_status         = 'excluded',
                feedback_to_dfp            = FALSE,
                severity                   = %s,
                status                     = 'new',
                updated_at                 = NOW(),
                root_cause                 = %s,
                sub_category               = %s,
                classification_confidence  = %s,
                classification_reasoning   = %s,
                classified_at              = %s
            WHERE anomaly_id = %s
        """,
            (
                MIDBAND_CONF,
                reasoning,
                now,
                MIDBAND_BY,
                sev,
                root_cause,
                sub_category,
                MIDBAND_CONF,
                cls_reasoning,
                now,
                row["anomaly_id"],
            ),
        )
        lower_count += 1
    conn.commit()
    print(f"Labeled {lower_count} midband-lower rows as TRUE_POSITIVE (confidence 0.65)")
    print(f"   Total midband band labeled: {upper_count + lower_count}")
    print("   These may be overwritten by LLM batch_labeler when it processes them.")
    return upper_count, lower_count


# ── Helpers ───────────────────────────────────────────────────────────────────


def print_preview(cur):
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE anomaly_score >= %s AND is_anomaly IS NULL) AS will_tp,
            COUNT(*) FILTER (WHERE anomaly_score <  %s AND is_anomaly IS NULL) AS will_fp,
            COUNT(*) FILTER (WHERE anomaly_score >= %s AND anomaly_score < %s AND is_anomaly IS NULL) AS will_skip,
            COUNT(*) FILTER (WHERE is_anomaly IS NOT NULL) AS already_labeled
        FROM enriched_anomalies
    """,
        (TP_THRESHOLD, FP_THRESHOLD, FP_THRESHOLD, TP_THRESHOLD),
    )
    r = cur.fetchone()
    print(f"\n{'=' * 60}")
    print("  Heuristic Labeling Preview")
    print(f"{'=' * 60}")
    print(f"  Will label TRUE_POSITIVE  (score >= {TP_THRESHOLD})  : {r['will_tp']:5d}")
    print(f"  Will label FALSE_POSITIVE (score <  {FP_THRESHOLD})   : {r['will_fp']:5d}")
    print(f"  Will SKIP  (no ambiguous band with new thresholds)  : {r['will_skip']:5d}")
    print(f"  Already labeled (skipped)               : {r['already_labeled']:5d}")
    print("  (--label-ambiguous handles any stragglers in 2.5-5.0 MEDIUM band as TP)")
    print(f"{'=' * 60}")
    print("  Columns updated: is_anomaly, validation_confidence, validation_reasoning,")
    print("                   validated_at, validated_by, dfp_retrain_status,")
    print("                   feedback_to_dfp, status, severity, updated_at")
    print("  TP also gets:    root_cause, sub_category, classification_confidence,")
    print("                   classification_reasoning, classified_at (heuristic)")
    print("  Left NULL:       risk_score, risk_factors (Stage 2 risk scorer)")
    print(f"{'=' * 60}\n")
    return r["will_tp"], r["will_fp"], r["will_skip"]


def print_stats(cur):
    cur.execute(
        """
        SELECT
            COUNT(*)                                                               AS total,
            COUNT(*) FILTER (WHERE is_anomaly IS NULL)                             AS unlabeled,
            COUNT(*) FILTER (WHERE is_anomaly = TRUE)                              AS true_anomaly,
            COUNT(*) FILTER (WHERE is_anomaly = FALSE)                             AS false_positive,
            COUNT(*) FILTER (WHERE validated_by = %s)                              AS heuristic,
            COUNT(*) FILTER (WHERE validated_by = 'heuristic_midband')             AS heuristic_midband,
            COUNT(*) FILTER (WHERE validated_by = 'ai_auto_labeler')               AS llm_labeled,
            COUNT(*) FILTER (WHERE is_anomaly = TRUE AND root_cause IS NOT NULL)   AS with_root_cause,
            COUNT(*) FILTER (WHERE is_anomaly = TRUE AND root_cause IS NULL)       AS missing_root_cause,
            AVG(validation_confidence)
                FILTER (WHERE validation_confidence IS NOT NULL)                  AS avg_conf
        FROM enriched_anomalies
    """,
        (VALIDATED_BY,),
    )
    r = cur.fetchone()
    print(f"\n{'=' * 60}")
    print("  enriched_anomalies — Final Label Stats")
    print(f"{'=' * 60}")
    print(f"  Total                    : {r['total']}")
    print(f"  ├─ Unlabeled             : {r['unlabeled']}")
    print(f"  ├─ TRUE ANOMALY          : {r['true_anomaly']}")
    print(f"  │   ├─ root_cause set    : {r['with_root_cause']}")
    print(f"  │   └─ root_cause NULL   : {r['missing_root_cause']}")
    print(f"  ├─ FALSE POSITIVE        : {r['false_positive']}")
    print(f"  ├─ Heuristic (high-conf) : {r['heuristic']}")
    print(f"  ├─ Heuristic (midband)   : {r['heuristic_midband']} (low-conf, LLM will overwrite)")
    print(f"  ├─ LLM labeled           : {r['llm_labeled']}")
    avg = r["avg_conf"]
    print(f"  └─ Avg confidence    : {avg:.3f}" if avg else "  └─ Avg confidence    : N/A")
    print(f"{'=' * 60}")

    # Root cause distribution for TPs
    cur.execute(
        """
        SELECT root_cause, sub_category, COUNT(*) AS n
        FROM enriched_anomalies
        WHERE is_anomaly = TRUE AND root_cause IS NOT NULL
        GROUP BY root_cause, sub_category
        ORDER BY n DESC
    """
    )
    rows = cur.fetchall()
    if rows:
        print("  Root Cause Distribution (TRUE POSITIVES):")
        for row in rows:
            print(f"    {row['root_cause']} / {row['sub_category']}: {row['n']}")
    print(f"{'=' * 60}\n")


def apply_labels(conn, dry_run: bool, relabel: bool):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    now = datetime.now(timezone.utc)

    tp_count = 0
    fp_count = 0

    # ── TRUE_POSITIVE pass ────────────────────────────────────────────────────
    where_extra = "" if relabel else "AND is_anomaly IS NULL"
    cur.execute(
        f"""
        SELECT anomaly_id, anomaly_score,
               raw_detection->>'top_features' AS top_features
        FROM enriched_anomalies
        WHERE anomaly_score >= %s {where_extra}
        ORDER BY anomaly_score DESC
    """,
        (TP_THRESHOLD,),
    )
    tp_rows = cur.fetchall()

    if dry_run:
        print(f"[DRY RUN] Would label {len(tp_rows)} rows as TRUE_POSITIVE")
    else:
        for row in tp_rows:
            score = float(row["anomaly_score"])
            sev = _severity(score)
            val_reasoning = REASONING_TP.format(score=score, thresh=TP_THRESHOLD, sev=sev)
            root_cause, sub_category, cls_reasoning = _root_cause_from_features(row["top_features"] or "")
            cur.execute(
                """
                UPDATE enriched_anomalies
                SET
                    is_anomaly                 = TRUE,
                    validation_confidence      = %s,
                    validation_reasoning       = %s,
                    validated_at               = %s,
                    validated_by               = %s,
                    dfp_retrain_status         = 'excluded',
                    feedback_to_dfp            = FALSE,
                    severity                   = %s,
                    status                     = 'new',
                    updated_at                 = NOW(),
                    root_cause                 = %s,
                    sub_category               = %s,
                    classification_confidence  = %s,
                    classification_reasoning   = %s,
                    classified_at              = %s
                WHERE anomaly_id = %s
            """,
                (
                    CONFIDENCE,
                    val_reasoning,
                    now,
                    VALIDATED_BY,
                    sev,
                    root_cause,
                    sub_category,
                    0.70,
                    cls_reasoning,
                    now,
                    row["anomaly_id"],
                ),
            )
            tp_count += 1
        conn.commit()
        print(f"Labeled {tp_count} rows as TRUE_POSITIVE (with heuristic root_cause)")

    # ── FALSE_POSITIVE pass ───────────────────────────────────────────────────
    cur.execute(
        f"""
        SELECT anomaly_id, anomaly_score
        FROM enriched_anomalies
        WHERE anomaly_score < %s {where_extra}
        ORDER BY anomaly_score ASC
    """,
        (FP_THRESHOLD,),
    )
    fp_rows = cur.fetchall()

    if dry_run:
        print(f"[DRY RUN] Would label {len(fp_rows)} rows as FALSE_POSITIVE")
    else:
        for row in fp_rows:
            score = float(row["anomaly_score"])
            reasoning = REASONING_FP.format(score=score, thresh=FP_THRESHOLD)
            cur.execute(
                """
                UPDATE enriched_anomalies
                SET
                    is_anomaly            = FALSE,
                    validation_confidence = %s,
                    validation_reasoning  = %s,
                    validated_at          = %s,
                    validated_by          = %s,
                    dfp_retrain_status    = 'queued',
                    feedback_to_dfp       = TRUE,
                    severity              = 'LOW',
                    status                = 'resolved',
                    updated_at            = NOW()
                WHERE anomaly_id = %s
            """,
                (CONFIDENCE, reasoning, now, VALIDATED_BY, row["anomaly_id"]),
            )
            fp_count += 1
        conn.commit()
        print(f"Labeled {fp_count} rows as FALSE_POSITIVE")

    # ── Ambiguous band summary ─────────────────────────────────────────────────
    cur.execute(
        """
        SELECT COUNT(*) FROM enriched_anomalies
        WHERE anomaly_score >= %s AND anomaly_score < %s AND is_anomaly IS NULL
    """,
        (FP_THRESHOLD, TP_THRESHOLD),
    )
    medium_count = cur.fetchone()["count"]
    print(f"\n{medium_count} ambiguous records (score {FP_THRESHOLD}-{TP_THRESHOLD}) left unlabeled.")
    if medium_count > 0:
        print("   Run LLM labeling on them with:")
        print(f"   python modules/ai/auto_labeling/batch_labeler.py --limit {medium_count}")

    return tp_count, fp_count, medium_count


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Heuristic score-based labeling for enriched_anomalies")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without writing")
    parser.add_argument("--stats", action="store_true", help="Print stats after labeling")
    parser.add_argument("--relabel", action="store_true", help="Overwrite existing labels (use with care)")
    parser.add_argument(
        "--label-ambiguous",
        action="store_true",
        help="Also label the 3-10 ambiguous band at low confidence (0.55) for Stage 2 diversity. "
        "score 5-10 → TP, score 3-5 → FP. Will be overwritten by LLM batch_labeler.",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Stats-only mode: no labeling flags passed alongside --stats
    stats_only = args.stats and not args.dry_run and not args.relabel and not args.label_ambiguous
    if stats_only:
        print_stats(cur)
        conn.close()
        return

    print_preview(cur)

    if args.dry_run:
        print("Dry run complete — no rows written.\n")
        if args.stats:
            print_stats(cur)
        conn.close()
        return

    confirm = input("Apply labels? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        if args.stats:
            print_stats(cur)
        conn.close()
        return

    apply_labels(conn, dry_run=False, relabel=args.relabel)

    if args.label_ambiguous:
        apply_ambiguous_labels(conn, relabel=args.relabel)

    if args.stats:
        print_stats(cur)

    conn.close()


if __name__ == "__main__":
    main()
