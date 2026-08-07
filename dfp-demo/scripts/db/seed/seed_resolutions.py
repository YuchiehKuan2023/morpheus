#!/usr/bin/env python3
"""
Seed Resolution Data Script

Randomly assigns three statuses to enriched_anomalies to simulate a realistic
SOC queue:

  Target distribution:
    resolved → 32%  (closed, with analyst, verdict, notes, resolved_at)
    pending  → 20%  (assigned to analyst, awaiting review)
    new      → 48%  (just detected, unassigned)

  Skips rows already marked resolved (with analyst_verdict).

Usage:
    # Dry-run — show what would change, no writes
    python scripts/utils/seed_resolutions.py --dry-run

    # Apply with default rates
    python scripts/utils/seed_resolutions.py

    # Override resolved % only (pending rate stays at --pending-rate default)
    python scripts/utils/seed_resolutions.py --rate 0.25

    # Reset everything back to 'new' / NULL fields (undo)
    python scripts/utils/seed_resolutions.py --reset
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[3] / ".env", override=False)
except ImportError:
    pass

import psycopg2
import psycopg2.extras

# ── DB config ─────────────────────────────────────────────────────────────────
from modules.utils.db import get_db_params

DB_CONFIG = get_db_params()

# ── Target rates (fraction of all eligible anomalies) ────────────────────────

DEFAULT_RESOLVED_RATE = 0.32
DEFAULT_PENDING_RATE = 0.20
# The remainder (~0.48) stays as 'investigating'

# ── Realistic resolution note templates per root_cause / fallback ─────────────

NOTES_BY_ROOT_CAUSE: dict[str, list[str]] = {
    "Account Takeover": [
        "Confirmed account takeover attempt. Password reset forced, MFA re-enrolled. Session tokens invalidated.",
        "User contacted — travel confirmed genuine. Account marked safe after manual verification.",
        "Credential reuse from third-party breach confirmed. Password rotated, breach notification sent.",
    ],
    "Credential Stuffing": [
        "Bot-driven credential stuffing blocked at WAF. No successful logins. Alert closed.",
        "Repeated failed login bursts from known Tor exit nodes. IP blocklist updated.",
        "Automated attack signature matched. Rate limiting applied. No compromise detected.",
    ],
    "Privilege Escalation": [
        "Reviewed with line manager — temporary admin access was pre-approved for project work. Resolved.",
        "Privilege change rolled back. Access reviewed by IAM team. Root cause: misconfigured role assignment.",
        "Elevation abuse confirmed. User account suspended. Incident ticket raised in ServiceNow.",
    ],
    "Data Exfiltration": [
        "Large download verified as approved data migration. Ticket #DM-4821 referenced. False positive.",
        "SharePoint export reviewed — content was non-sensitive marketing material. Closed as benign.",
        "DLP alert confirmed genuine. Legal hold placed. Evidence preserved. Escalated to CISO.",
    ],
    "Insider Threat": [
        "HR and legal consulted. User activity within policy. No further action required.",
        "Departure-related data access confirmed by manager. Files moved to offboarding folder. Closed.",
        "Pattern consistent with a disgruntled employee. Monitoring escalated. Account rights trimmed.",
    ],
    "Geographic Anomaly": [
        "User confirmed travelling to the flagged location. VPN usage noted. Alert false positive.",
        "Login from unusual region traced to approved contractor work. Closed after verification.",
        "Access from foreign IP investigated — VPN misconfiguration. IT helpdesk notified.",
    ],
    "Impossible Travel": [
        "Dual session from two countries simultaneously. Second session from VPN. Confirmed not compromise.",
        "Impossible travel confirmed as credential sharing between colleagues. Policy violation issued.",
        "Travel timeline physically impossible. Account suspended pending forensic review.",
    ],
    "Unusual Hours": [
        "User confirmed working late due to project deadline. Manager confirmed. Alert closed.",
        "After-hours access from corporate network. Badge records corroborate on-site presence. Closed.",
        "Automated overnight job running under user credentials. IT agreed to move to service account.",
    ],
    "Mass Download": [
        "Bulk export approved by data governance team for quarterly audit. Ticket closed.",
        "Download volume anomaly caused by backup client. Asset tag confirmed in CMDB. False positive.",
        "Exfiltration confirmed. USB device seized. DLP policy updated to block USB on endpoint.",
    ],
}

NOTES_FALLBACK = [
    "Investigated and confirmed as benign. No further action required.",
    "False positive — activity consistent with user's normal work pattern.",
    "Reviewed with user and manager. Explained behaviour. Closed.",
    "Alert reviewed: scheduled maintenance window explains the activity. Closed.",
    "Low-risk deviation. Documented and closed after supervisor sign-off.",
    "Activity matched approved change request CR-{n}. Closed.",
    "Verified with IT: system configuration change accounts for anomaly. Resolved.",
    "User on approved travel. Location and device verified. Alert closed.",
    "Duplicate alert — primary ticket already resolved upstream. Closed as duplicate.",
    "Risk accepted by business owner. Compensating controls in place.",
]


def _pick_note(root_cause: str | None) -> str:
    pool = NOTES_BY_ROOT_CAUSE.get(root_cause or "", NOTES_FALLBACK)
    note = random.choice(pool)
    # Fill any placeholder tokens
    note = note.replace("{n}", str(random.randint(1000, 9999)))
    return note


def _resolved_at(anomaly_ts: datetime) -> datetime:
    """Return a resolved_at timestamp between 30 min and 72 h after the anomaly."""
    delta_hours = random.uniform(0.5, 72.0)
    return anomaly_ts + timedelta(hours=delta_hours)


# ── Main ──────────────────────────────────────────────────────────────────────


def run(dry_run: bool, resolved_rate: float, pending_rate: float, reset: bool) -> None:
    if resolved_rate + pending_rate > 1.0:
        raise ValueError("--rate + --pending-rate cannot exceed 1.0")

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # ── RESET mode ────────────────────────────────────────────────────
            if reset:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'resolved') AS resolved,
                        COUNT(*) FILTER (WHERE status = 'pending')  AS pending
                    FROM enriched_anomalies
                """)
                counts = cur.fetchone()
                if dry_run:
                    print(
                        f"[dry-run] Would reset {counts['resolved']} resolved + "
                        f"{counts['pending']} pending rows back to 'new'."
                    )
                    return
                cur.execute("""
                    UPDATE enriched_anomalies
                    SET status           = 'new',
                        assigned_to      = NULL,
                        resolution_notes = NULL,
                        analyst_verdict  = NULL,
                        analyst_notes    = NULL,
                        reviewed_by      = NULL,
                        reviewed_at      = NULL,
                        resolved_at      = NULL,
                        updated_at       = NOW()
                    WHERE status IN ('resolved', 'pending')
                """)
                print(f"Reset {cur.rowcount} rows to status='new'.")
                conn.commit()
                return

            # ── Load analysts ─────────────────────────────────────────────────
            cur.execute("""
                SELECT id, display_name, analyst_role, level
                FROM analyst_users
                WHERE is_active = TRUE
                ORDER BY id
            """)
            analysts = cur.fetchall()
            if not analysts:
                print("ERROR: No active rows in analyst_users. Run the users seed script first.")
                return

            print(f"Found {len(analysts)} active analysts.")

            # Tier analysts by severity using permissions constants
            sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
            from scripts.constants.permissions import ANALYST_LEVELS

            def _analysts_for(sev: str) -> list:
                allowed_levels = [
                    level for level, entry in ANALYST_LEVELS.items() if sev in entry["allowed_severities"]
                ]
                matches = [a for a in analysts if a["level"] in allowed_levels]
                return matches or list(analysts)

            # ── Load all eligible anomalies ───────────────────────────────────
            cur.execute("""
                SELECT anomaly_id, severity, root_cause, timestamp
                FROM enriched_anomalies
                WHERE analyst_verdict IS NULL
                ORDER BY timestamp
            """)
            rows = cur.fetchall()
            total = len(rows)
            print(f"Eligible anomalies (no analyst verdict yet): {total}")

            # Shuffle and partition by target rates
            indices = list(range(total))
            random.shuffle(indices)

            n_resolved = round(total * resolved_rate)
            n_pending = round(total * pending_rate)
            # remainder stays as 'new'

            resolved_ids = {rows[i]["anomaly_id"] for i in indices[:n_resolved]}
            pending_ids = {rows[i]["anomaly_id"] for i in indices[n_resolved : n_resolved + n_pending]}

            print(
                f"Target: {n_resolved} resolved ({resolved_rate * 100:.0f}%), "
                f"{n_pending} pending ({pending_rate * 100:.0f}%), "
                f"{total - n_resolved - n_pending} new "
                f"({(1 - resolved_rate - pending_rate) * 100:.0f}%)"
            )

            if dry_run:
                sample_resolved = [r for r in rows if r["anomaly_id"] in resolved_ids][:3]
                print("\n[dry-run] Sample resolved:")
                for r in sample_resolved:
                    print(f"  {r['anomaly_id']}  [{r['severity']}]  {r['root_cause']}")
                print("\n[dry-run] No changes written.")
                return

            # ── Apply resolved ────────────────────────────────────────────────
            for row in rows:
                aid = row["anomaly_id"]
                if aid in resolved_ids:
                    analyst = random.choice(_analysts_for((row["severity"] or "LOW").upper()))
                    ts = row["timestamp"]
                    res_at = _resolved_at(ts) if ts else datetime.now(timezone.utc)
                    cur.execute(
                        """
                        UPDATE enriched_anomalies
                        SET status           = 'resolved',
                            assigned_to      = %(assigned_to)s,
                            analyst_verdict  = 'confirmed',
                            analyst_notes    = %(notes)s,
                            resolution_notes = %(notes)s,
                            reviewed_by      = %(assigned_to)s,
                            reviewed_at      = %(resolved_at)s,
                            resolved_at      = %(resolved_at)s,
                            updated_at       = NOW()
                        WHERE anomaly_id = %(anomaly_id)s
                    """,
                        {
                            "anomaly_id": aid,
                            "assigned_to": analyst["id"],
                            "notes": _pick_note(row["root_cause"]),
                            "resolved_at": res_at,
                        },
                    )
                elif aid in pending_ids:
                    analyst = random.choice(_analysts_for((row["severity"] or "LOW").upper()))
                    cur.execute(
                        """
                        UPDATE enriched_anomalies
                        SET status           = 'pending',
                            assigned_to      = %(assigned_to)s,
                            resolution_notes = NULL,
                            resolved_at      = NULL,
                            updated_at       = NOW()
                        WHERE anomaly_id = %(anomaly_id)s
                    """,
                        {"anomaly_id": aid, "assigned_to": analyst["id"]},
                    )
                else:
                    # ensure status is 'new' (reset any prior seeds)
                    cur.execute(
                        """
                        UPDATE enriched_anomalies
                        SET status      = 'new',
                            assigned_to = NULL,
                            updated_at  = NOW()
                        WHERE anomaly_id = %(anomaly_id)s
                          AND status != 'new'
                    """,
                        {"anomaly_id": aid},
                    )

            conn.commit()
            print("Done.")

            # ── Summary stats ─────────────────────────────────────────────────
            cur.execute("""
                SELECT
                    status,
                    COUNT(*) AS n,
                    ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS pct
                FROM enriched_anomalies
                GROUP BY status
                ORDER BY status
            """)
            print("\nStatus distribution:")
            print(f"  {'Status':<16} {'Count':>6} {'%':>6}")
            print(f"  {'-' * 30}")
            for r in cur.fetchall():
                print(f"  {r['status']:<16} {r['n']:>6} {r['pct']:>5}%")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed resolution data into enriched_anomalies.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to the database.")
    parser.add_argument(
        "--rate",
        type=float,
        default=DEFAULT_RESOLVED_RATE,
        metavar="0.0-1.0",
        help=f"Fraction to mark resolved (default: {DEFAULT_RESOLVED_RATE}).",
    )
    parser.add_argument(
        "--pending-rate",
        type=float,
        default=DEFAULT_PENDING_RATE,
        metavar="0.0-1.0",
        help=f"Fraction to mark pending (default: {DEFAULT_PENDING_RATE}). Remainder → new.",
    )
    parser.add_argument("--reset", action="store_true", help="Reset all resolved/pending rows back to 'new'.")
    args = parser.parse_args()

    if not (0.0 <= args.rate <= 1.0):
        parser.error("--rate must be between 0.0 and 1.0")
    if not (0.0 <= args.pending_rate <= 1.0):
        parser.error("--pending-rate must be between 0.0 and 1.0")
    if args.rate + args.pending_rate > 1.0:
        parser.error("--rate + --pending-rate cannot exceed 1.0")

    random.seed(42)  # reproducible run — remove for different shuffles each time
    run(dry_run=args.dry_run, resolved_rate=args.rate, pending_rate=args.pending_rate, reset=args.reset)
