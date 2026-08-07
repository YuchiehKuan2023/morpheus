#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# Load test: 10 concurrent agentic chat sessions
# ────────────────────────────────────────────────────────────────
# Usage:   ./scripts/tests/load_test_chat.sh [BASE_URL] [CONCURRENCY]
# Example: ./scripts/tests/load_test_chat.sh http://localhost:8001 10
#
# Each virtual session:
#   1. Creates a new chat session
#   2. Sends 3 queries (simple → moderate → complex)
#   3. Records latency for each query
#   4. Deletes the session
#
# Results are printed as a summary table at the end.
# ────────────────────────────────────────────────────────────────
set -euo pipefail

BASE="${1:-http://localhost:8001}"
API="${BASE}/api/v1/chat"
CONCURRENCY="${2:-10}"
RESULTS_DIR="$(mktemp -d)"
QUERIES=(
  "What is the current risk level?"
  "Show me alice@co.com's anomaly timeline and baseline"
  "Compare the risk profiles of the top 5 critical anomalies and explain their root causes"
)

run_session() {
  local idx=$1
  local out="${RESULTS_DIR}/session_${idx}.log"

  # Create session
  local session
  session=$(curl -sf -X POST "${API}/sessions" \
    -H "Content-Type: application/json" \
    -d "{\"title\": \"Load test ${idx}\"}" 2>/dev/null) || { echo "FAIL create ${idx}" >> "$out"; return 1; }
  local sid
  sid=$(echo "$session" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)

  if [[ -z "$sid" ]]; then
    echo "FAIL parse session_id ${idx}" >> "$out"
    return 1
  fi

  echo "session_id=${sid}" >> "$out"

  # Send queries
  for qi in "${!QUERIES[@]}"; do
    local q="${QUERIES[$qi]}"
    local t0
    t0=$(python3 -c "import time; print(time.time())")

    local resp
    resp=$(curl -sf -X POST "${API}/query" \
      -H "Content-Type: application/json" \
      -d "{\"session_id\": ${sid}, \"query\": $(python3 -c "import json; print(json.dumps('$q'))")}" \
      --max-time 60 2>/dev/null) || resp=""

    local t1
    t1=$(python3 -c "import time; print(time.time())")

    local latency
    latency=$(python3 -c "print(round(($t1 - $t0) * 1000))")

    if [[ -n "$resp" ]]; then
      local answer_len
      answer_len=$(echo "$resp" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('answer','')))" 2>/dev/null || echo "0")
      echo "query_${qi}=OK latency_ms=${latency} answer_len=${answer_len}" >> "$out"
    else
      echo "query_${qi}=FAIL latency_ms=${latency}" >> "$out"
    fi
  done

  # Cleanup session
  curl -sf -X DELETE "${API}/sessions/${sid}" > /dev/null 2>&1 || true
  echo "cleanup=done" >> "$out"
}

echo "═══════════════════════════════════════════════════════════"
echo "  Agentic Chat Load Test"
echo "  Base URL:    ${API}"
echo "  Concurrency: ${CONCURRENCY} sessions"
echo "  Queries/session: ${#QUERIES[@]}"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Starting ${CONCURRENCY} concurrent sessions..."
echo ""

# Launch sessions in parallel
pids=()
for i in $(seq 1 "$CONCURRENCY"); do
  run_session "$i" &
  pids+=($!)
done

# Wait for all
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" 2>/dev/null || ((failed++))
done

# Collect results
echo ""
echo "───────────────────────────────────────────────────────────"
echo "  RESULTS"
echo "───────────────────────────────────────────────────────────"
printf "%-8s %-8s %-12s %-12s %-12s\n" "Session" "Status" "Query 1 ms" "Query 2 ms" "Query 3 ms"
echo "───────────────────────────────────────────────────────────"

total_ok=0
total_fail=0
latencies=()

for i in $(seq 1 "$CONCURRENCY"); do
  logfile="${RESULTS_DIR}/session_${i}.log"
  if [[ ! -f "$logfile" ]]; then
    printf "%-8s %-8s %-12s %-12s %-12s\n" "$i" "MISS" "-" "-" "-"
    ((total_fail++))
    continue
  fi

  q0=$(grep "query_0=" "$logfile" 2>/dev/null | head -1 || echo "")
  q1=$(grep "query_1=" "$logfile" 2>/dev/null | head -1 || echo "")
  q2=$(grep "query_2=" "$logfile" 2>/dev/null | head -1 || echo "")

  status="OK"
  l0="-"; l1="-"; l2="-"

  if [[ "$q0" == *"OK"* ]]; then
    l0=$(echo "$q0" | grep -oE 'latency_ms=[0-9]+' | cut -d= -f2)
    latencies+=("$l0")
  else
    status="FAIL"; ((total_fail++))
  fi

  if [[ "$q1" == *"OK"* ]]; then
    l1=$(echo "$q1" | grep -oE 'latency_ms=[0-9]+' | cut -d= -f2)
    latencies+=("$l1")
  else
    [[ "$status" == "OK" ]] && { status="PARTIAL"; ((total_fail++)); }
  fi

  if [[ "$q2" == *"OK"* ]]; then
    l2=$(echo "$q2" | grep -oE 'latency_ms=[0-9]+' | cut -d= -f2)
    latencies+=("$l2")
  else
    [[ "$status" == "OK" ]] && { status="PARTIAL"; ((total_fail++)); }
  fi

  [[ "$status" == "OK" ]] && ((total_ok++))
  printf "%-8s %-8s %-12s %-12s %-12s\n" "$i" "$status" "${l0}ms" "${l1}ms" "${l2}ms"
done

echo "───────────────────────────────────────────────────────────"

# Summary stats
if [[ ${#latencies[@]} -gt 0 ]]; then
  avg=$(python3 -c "
import sys
vals = [${latencies[*]}]
vals.sort()
n = len(vals)
print(f'Avg: {sum(vals)//n}ms  P50: {vals[n//2]}ms  P95: {vals[int(n*0.95)]}ms  Max: {vals[-1]}ms')
" 2>/dev/null || echo "N/A")
  echo "Latency: $avg"
fi

echo "Sessions: ${total_ok} OK, ${total_fail} failed (of ${CONCURRENCY})"
echo ""

# Cleanup
rm -rf "$RESULTS_DIR"

# Exit code
[[ $total_fail -eq 0 ]] && exit 0 || exit 1
