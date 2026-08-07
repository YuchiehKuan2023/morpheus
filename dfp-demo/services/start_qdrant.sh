#!/bin/bash
# Start Qdrant vector database for AI modules
# Usage: ./services/start_qdrant.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
QDRANT_BIN="$PROJECT_ROOT/bin/qdrant"
QDRANT_CONFIG="$PROJECT_ROOT/config/qdrant.yaml"
STORAGE_PATH="$PROJECT_ROOT/data/ai/qdrant"
PID_FILE="$PROJECT_ROOT/data/ai/qdrant/qdrant.pid"
LOG_FILE="$PROJECT_ROOT/data/logs/qdrant.log"

echo "=== Starting Qdrant Vector Database ==="
echo "Binary: $QDRANT_BIN"
echo "Storage: $STORAGE_PATH"
echo "API: http://localhost:6333"
echo "gRPC: http://localhost:6334"
echo ""

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Qdrant is already running (PID: $PID)"
        echo "   Stop it first with: ./services/stop_qdrant.sh"
        exit 1
    else
        echo "Cleaning up stale PID file..."
        rm "$PID_FILE"
    fi
fi

# Check if Qdrant binary exists
if [ ! -f "$QDRANT_BIN" ]; then
    echo "Error: Qdrant binary not found at $QDRANT_BIN"
    echo "Please install Qdrant first. See README for installation instructions."
    exit 1
fi

# Check if binary is executable
if [ ! -x "$QDRANT_BIN" ]; then
    echo "Error: Qdrant binary is not executable"
    echo "Run: chmod +x $QDRANT_BIN"
    exit 1
fi

# Create storage directory if it doesn't exist
mkdir -p "$STORAGE_PATH"

# Start Qdrant in background with config file
echo "Starting Qdrant..."
cd "$PROJECT_ROOT"
"$QDRANT_BIN" \
    --config-path "$QDRANT_CONFIG" \
    > "$LOG_FILE" 2>&1 &

QDRANT_PID=$!
echo "$QDRANT_PID" > "$PID_FILE"

echo "Qdrant started successfully!"
echo "   PID: $QDRANT_PID"
echo "   Log: $LOG_FILE"
echo ""
echo "API endpoints:"
echo "  - REST API: http://localhost:6333"
echo "  - Dashboard: http://localhost:6333/dashboard"
echo "  - gRPC: http://localhost:6334"
echo ""
echo "Stop with: ./services/stop_qdrant.sh"
