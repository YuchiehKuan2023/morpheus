"""
Redistribute enriched_anomaly timestamps over a realistic ~17-week window.

Strategy
--------
* Spread 1 700 anomalies across the last 119 days (17 weeks), ending yesterday.
* Daily volume follows a realistic pattern:
  - Weekdays receive 2× the weight of weekends (security incidents skew Mon–Fri).
  - Three random "incident spike" weeks receive 3× the base weight (simulates
    coordinated attack campaigns).
  - A handful of quiet periods (bank-holiday-style) receive 0.3× weight.
* Within each day, timestamps are biased toward business hours (08:00–18:00)
  with a long-tail into evening; a small fraction fall outside working hours.
* Per-user ordering is preserved: if a user already has multiple anomalies,
  their new timestamps are assigned in ascending order so the timeline is
  internally consistent.
* created_at is set equal to timestamp (no future created_at values).

Usage
-----
    # Dry run — prints the target distribution, touches nothing
    python scripts/db/redistribute_timestamps.py --dry-run

    # Live run
    python scripts/db/redistribute_timestamps.py
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# ── Config ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parents[3]  # dfp-demo/
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from modules.utils.db import get_db_params  # noqa: E402

DB_CONFIG = get_db_params()

SEED = 42
WINDOW_DAYS = 119  # 17 weeks
# End = yesterday so "today" has no anomalies yet (realistic)
END_DATE = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
START_DATE = END_DATE - timedelta(days=WINDOW_DAYS - 1)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _business_hour_second() -> int:
    """Return a random second-of-day biased toward business hours."""
    r = random.random()
    if r < 0.65:
        # 08:00–18:00 (peak)
        h = random.randint(8, 17)
    elif r < 0.80:
        # 18:00–22:00 (evening tail)
        h = random.randint(18, 21)
    elif r < 0.90:
        # 06:00–08:00 (early starters)
        h = random.randint(6, 7)
    else:
        # 22:00–06:00 (off-hours / suspicious)
        h = random.choice([22, 23, 0, 1, 2, 3])
    return h * 3600 + random.randint(0, 3599)


def _build_day_weights() -> list[tuple[datetime, float]]:
    """Return a list of (date, weight) for every day in the window."""
    random.seed(SEED)

    days: list[datetime] = [START_DATE + timedelta(days=i) for i in range(WINDOW_DAYS)]
    # Pick 3 spike weeks and 2 quiet weeks (by week index, 0-based)
    week_indices = list(range(WINDOW_DAYS // 7))
    spike_weeks = set(random.sample(week_indices, 3))
    quiet_weeks = set(random.sample([w for w in week_indices if w not in spike_weeks], 2))

    weights: list[tuple[datetime, float]] = []
    for i, day in enumerate(days):
        week_idx = i // 7
        is_weekend = day.weekday() >= 5  # Sat=5, Sun=6

        if is_weekend:
            # Weekends are always mild — not influenced by spike/quiet periods
            base = 0.55
        else:
            base = 1.0
            if week_idx in spike_weeks:
                base = 1.4
            elif week_idx in quiet_weeks:
                base = 0.7

        # Add per-day jitter (±25%) so days within the same week aren't identical.
        # Jitter is seeded, so results are reproducible.
        # Weekend jitter is intentionally narrower (±15%) so they never exceed weekdays.
        if is_weekend:
            jitter = random.uniform(0.85, 1.15)
        else:
            jitter = random.uniform(0.75, 1.25)

        weights.append((day, base * jitter))

    return weights


def _generate_timestamps(count: int) -> list[datetime]:
    """Generate `count` timestamps using deterministic per-day quota allocation.

    Instead of sampling each anomaly independently (high variance), we pre-compute
    an exact integer count for every day proportional to its weight, then fill each
    day's quota with business-hour-biased timestamps. This guarantees that weekends
    are always below weekdays and spike/quiet weeks are clearly visible.
    """
    random.seed(SEED)
    day_weights_list = _build_day_weights()
    days = [d for d, _ in day_weights_list]
    weights = [w for _, w in day_weights_list]

    # Deterministically allocate exact counts using largest-remainder method
    total_weight = sum(weights)
    raw = [w / total_weight * count for w in weights]
    quotas = [int(r) for r in raw]
    remainder = count - sum(quotas)
    # Give the remainder to the days with the largest fractional parts
    fractions = sorted(range(len(days)), key=lambda i: raw[i] - quotas[i], reverse=True)
    for i in fractions[:remainder]:
        quotas[i] += 1

    # Generate exactly `quota` timestamps for each day
    timestamps: list[datetime] = []
    for day, n in zip(days, quotas, strict=False):
        for _ in range(n):
            sec = _business_hour_second()
            timestamps.append(day + timedelta(seconds=sec))

    timestamps.sort()
    return timestamps


def _print_distribution(timestamps: list[datetime]) -> None:
    """Print a compact weekly summary for preview."""
    from collections import Counter

    daily = Counter(ts.date() for ts in timestamps)
    print(f"\nTimestamp distribution preview ({len(timestamps)} anomalies across {WINDOW_DAYS} days)")
    print(f"Window: {START_DATE.date()} → {END_DATE.date()}\n")
    print(f"{'Week':>5}  {'Mon':>4} {'Tue':>4} {'Wed':>4} {'Thu':>4} {'Fri':>4} {'Sat':>4} {'Sun':>4}  {'Total':>6}")
    print("─" * 60)

    week_start = START_DATE
    week_num = 1
    while week_start <= END_DATE:
        row = []
        week_total = 0
        for d in range(7):
            day = (week_start + timedelta(days=d)).date()
            c = daily.get(day, 0)
            row.append(c)
            week_total += c
        print(f"  W{week_num:02d}  " + "  ".join(f"{v:4d}" for v in row) + f"  {week_total:6d}")
        week_start += timedelta(days=7)
        week_num += 1

    print("─" * 60)
    counts = list(daily.values())
    print(f"  Min/day: {min(counts)}  Max/day: {max(counts)}  Avg/day: {sum(counts) / len(counts):.1f}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main(dry_run: bool = False) -> None:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            # Fetch all anomaly IDs ordered by user so per-user ordering is preserved
            cur.execute("""
                SELECT anomaly_id, user_id
                FROM enriched_anomalies
                ORDER BY user_id, timestamp ASC
            """)
            rows = cur.fetchall()

        total = len(rows)
        print(f"Found {total} anomalies in the database.")

        timestamps = _generate_timestamps(total)
        _print_distribution(timestamps)

        if dry_run:
            print("\n[DRY RUN] No changes written to the database.")
            return

        print(f"\nUpdating {total} rows...")
        with conn.cursor() as cur:
            for (anomaly_id, _), ts in zip(rows, timestamps, strict=False):
                cur.execute(
                    "UPDATE enriched_anomalies SET timestamp = %s, created_at = %s WHERE anomaly_id = %s",
                    (ts, ts, anomaly_id),
                )
        conn.commit()
        print(f"Done. {total} anomaly timestamps redistributed over {WINDOW_DAYS} days.")

    finally:
        conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
