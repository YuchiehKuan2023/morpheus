#!/bin/bash
# Stop Qdrant vector database
# Usage: ./services/stop_qdrant.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_ROOT/data/ai/qdrant/qdrant.pid"

echo "=== Stopping Qdrant Vector Database ==="

if [ ! -f "$PID_FILE" ]; then
    echo "Qdrant is not running (no PID file found)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "Qdrant process not found (stale PID: $PID)"
    rm "$PID_FILE"
    exit 0
fi

echo "Stopping Qdrant (PID: $PID)..."

# Send SIGTERM for graceful shutdown (allows Qdrant to flush data and clean up)
kill "$PID"

# Wait up to 10 seconds for process to terminate gracefully
for i in {1..10}; do
    if ! ps -p "$PID" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Force kill with SIGKILL if process didn't terminate gracefully
# This is a last resort that immediately terminates the process
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Force killing Qdrant (SIGKILL)..."
    kill -9 "$PID"
fi

rm "$PID_FILE"
echo "Qdrant stopped successfully!"
