#!/usr/bin/env bash
# =============================================================================
# migrate_to_timescaledb.sh
# =============================================================================
# One-shot data migration from native PG18 (port 5432) to the TimescaleDB
# Docker container (port 5433).
#
# Steps:
#   1. Verify both PostgreSQL instances are reachable
#   2. pg_dump the dfp_ai database from PG18
#   3. Restore the dump into TimescaleDB (port 5433)
#   4. Apply migration 013 to enable hypertables + policies
#   5. Verify row counts match between source and destination
#   6. Print next steps (update .env → restart services)
#
# Usage:
#   ./scripts/db/migrate_to_timescaledb.sh
#
#   Override source/target with env vars:
#   SRC_PORT=5432 DST_PORT=5433 POSTGRES_DB=dfp_ai ./scripts/db/migrate_to_timescaledb.sh
#
# Prerequisites:
#   - docker-compose up timescaledb  (start the TimescaleDB container first)
#   - pg_dump and psql from PostgreSQL 14+ must be on PATH
#     (they don't need to match the server version for dump/restore)
#
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
SRC_HOST="${POSTGRES_HOST:-localhost}"
SRC_PORT="${SRC_PORT:-5432}"
DST_HOST="${POSTGRES_HOST:-localhost}"
DST_PORT="${DST_PORT:-5433}"
DB="${POSTGRES_DB:-dfp_ai}"
USER="${POSTGRES_USER:-dfp_ai}"
PGPASSWORD="${POSTGRES_PASSWORD:-}"
export PGPASSWORD

# Prefer the versioned PG16 binaries to avoid client/server version mismatch.
# pg_dump must be >= the server version (16); the default PATH may have PG14.
for _pg_prefix in \
    /opt/homebrew/opt/postgresql@16/bin \
    /usr/local/opt/postgresql@16/bin \
    /opt/homebrew/opt/postgresql@17/bin \
    /usr/local/opt/postgresql@17/bin; do
    if [[ -x "$_pg_prefix/pg_dump" ]]; then
        export PATH="$_pg_prefix:$PATH"
        break
    fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION="$SCRIPT_DIR/migrations/013_timescaledb_hypertables.sql"
DUMP_FILE="${TMPDIR:-/tmp}/dfp_ai_$(date +%Y%m%d_%H%M%S).dump"

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Step helpers ───────────────────────────────────────────────────────────────
pg_src() { psql -h "$SRC_HOST" -p "$SRC_PORT" -U "$USER" -d "$DB" "$@"; }
pg_dst() { psql -h "$DST_HOST" -p "$DST_PORT" -U "$USER" -d "$DB" "$@"; }

row_count() {
    local host="$1" port="$2" table="$3"
    psql -h "$host" -p "$port" -U "$USER" -d "$DB" -t -c "SELECT COUNT(*) FROM $table;" \
        | tr -d '[:space:]'
}

# =============================================================================
echo ""
echo "============================================================"
echo "  DFP — Migrate to TimescaleDB"
echo "============================================================"
echo "  Source : $SRC_HOST:$SRC_PORT/$DB"
echo "  Target : $DST_HOST:$DST_PORT/$DB"
echo "  Dump   : $DUMP_FILE"
echo "============================================================"
echo ""

# ── 1. Verify source connectivity ─────────────────────────────────────────────
info "Step 1/5 — Verifying source PostgreSQL ($SRC_HOST:$SRC_PORT) ..."
psql -h "$SRC_HOST" -p "$SRC_PORT" -U "$USER" -d "$DB" -c "SELECT version();" -q \
    || die "Cannot connect to source PG18 on port $SRC_PORT. Is it running?"
info "  Source OK."

# ── 2. Verify target (TimescaleDB) connectivity ───────────────────────────────
info "Step 2/5 — Verifying target TimescaleDB ($DST_HOST:$DST_PORT) ..."
psql -h "$DST_HOST" -p "$DST_PORT" -U "$USER" -d "$DB" -c "SELECT version();" -q 2>/dev/null \
    || {
        # Database may not exist yet — try connecting without a specific DB
        warn "  Database '$DB' not found on port $DST_PORT — attempting to create it ..."
        PGPASSWORD="$PGPASSWORD" psql -h "$DST_HOST" -p "$DST_PORT" -U postgres \
            -c "CREATE DATABASE $DB OWNER $USER;" 2>/dev/null \
            || die "Cannot reach TimescaleDB on port $DST_PORT. Run: docker-compose up -d timescaledb"
    }
info "  Target OK."

# ── 3. Dump from PG18 ─────────────────────────────────────────────────────────
info "Step 3/5 — Dumping $DB from port $SRC_PORT ..."
info "  This may take a few minutes depending on data size ..."
pg_dump \
    -h "$SRC_HOST" \
    -p "$SRC_PORT" \
    -U "$USER" \
    -d "$DB" \
    --format=custom \
    --no-acl \
    --no-owner \
    --file="$DUMP_FILE"
DUMP_SIZE=$(du -sh "$DUMP_FILE" | cut -f1)
info "  Dump complete: $DUMP_FILE ($DUMP_SIZE)"

# ── 4. Restore into TimescaleDB ───────────────────────────────────────────────
info "Step 4/5 — Restoring into TimescaleDB on port $DST_PORT ..."
warn "  Existing data on port $DST_PORT will be replaced."
pg_restore \
    -h "$DST_HOST" \
    -p "$DST_PORT" \
    -U "$USER" \
    -d "$DB" \
    --no-acl \
    --no-owner \
    --clean \
    --if-exists \
    "$DUMP_FILE" \
    || warn "  pg_restore exited non-zero — this is usually harmless (duplicate DROP warnings). Continuing ..."

info "  Restore complete."

# ── 5. Apply TimescaleDB migration (013) ──────────────────────────────────────
info "Step 5/5 — Applying migration 013 (hypertables + policies) ..."
if [[ ! -f "$MIGRATION" ]]; then
    die "Migration file not found: $MIGRATION"
fi
pg_dst -f "$MIGRATION" -q
info "  Migration 013 applied."

# ── Verification ──────────────────────────────────────────────────────────────
echo ""
info "Verifying row counts ..."

TABLES=("enriched_anomalies" "user_training_events")
all_ok=true

for table in "${TABLES[@]}"; do
    src_count=$(row_count "$SRC_HOST" "$SRC_PORT" "$table" 2>/dev/null || echo "N/A")
    dst_count=$(row_count "$DST_HOST" "$DST_PORT" "$table" 2>/dev/null || echo "N/A")
    if [[ "$src_count" == "$dst_count" ]]; then
        info "  $table: $src_count rows  ✓"
    else
        warn "  $table: source=$src_count  target=$dst_count  — counts differ!"
        all_ok=false
    fi
done

# Check hypertable registration
HYPERTABLES=$(pg_dst -t -c "SELECT count(*) FROM timescaledb_information.hypertables;" 2>/dev/null | tr -d '[:space:]')
info "  Hypertables registered: $HYPERTABLES"

# Check continuous aggregate
CA=$(pg_dst -t -c "SELECT count(*) FROM timescaledb_information.continuous_aggregates;" 2>/dev/null | tr -d '[:space:]')
info "  Continuous aggregates:  $CA"

echo ""
echo "============================================================"
if $all_ok; then
    echo -e "  ${GREEN}Migration successful.${NC}"
else
    echo -e "  ${YELLOW}Migration complete with warnings — check row counts above.${NC}"
fi
echo "============================================================"
echo ""
echo "  Next steps to switch the application:"
echo ""
echo "  1. Edit your .env file and change:"
echo "       POSTGRES_PORT=5432   →   POSTGRES_PORT=5433"
echo ""
echo "  2. Restart all services:"
echo "       Kill the tmux windows running ai_orchestrator, run_agent_orchestrator,"
echo "       and inference_pipeline, then relaunch them."
echo "       Or if using docker-compose: docker-compose up -d"
echo ""
echo "  3. Verify the application still works:"
echo "       python scripts/tests/test_integration_full.py --list-users"
echo ""
echo "  4. Clean up the dump file when satisfied:"
echo "       rm $DUMP_FILE"
echo ""
echo "  The old PG18 database on port 5432 remains untouched until you"
echo "  are fully confident and choose to stop it."
echo "============================================================"
echo ""
