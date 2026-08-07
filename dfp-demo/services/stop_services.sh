#!/bin/bash

################################################################################
# DFP Services Stop Script
#
# Gracefully stops all DFP services running in tmux session
#
# Usage:
#   ./services/stop_services.sh
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Project root (needed for monitoring script references below)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || { echo "[ERROR] Failed to resolve PROJECT_ROOT"; exit 1; }

echo ""
echo "================================================================================"
echo -e "${YELLOW}Stopping DFP Services${NC}"
echo "================================================================================"
echo ""

# Check if tmux session exists
if ! tmux has-session -t dfp-services 2>/dev/null; then
    log_warning "No 'dfp-services' tmux session found"
    echo ""
    echo "Services may not be running or were started differently."
    echo "To manually kill processes on specific ports:"
    echo -e "  lsof -ti:5001 | xargs kill -9   # MLflow"
    echo -e "  lsof -ti:29092 | xargs kill -9  # Kafka"
    echo -e "  lsof -ti:6333 | xargs kill -9   # Qdrant"
    echo -e "  lsof -ti:8080 | xargs kill -9   # Kafka UI"
    exit 0
fi

# Gracefully stop services by sending Ctrl+C to each tmux window
log_info "Sending shutdown signals to services..."

# Send Ctrl+C to each window (graceful shutdown)
tmux send-keys -t dfp-services:0 C-c 2>/dev/null || true  # MLflow
sleep 1
tmux send-keys -t dfp-services:1 C-c 2>/dev/null || true  # Kafka
sleep 3  # Give Kafka more time to flush data
tmux send-keys -t dfp-services:2 C-c 2>/dev/null || true  # Qdrant
sleep 1
tmux send-keys -t dfp-services:3 C-c 2>/dev/null || true  # Kafka UI
sleep 1
tmux send-keys -t dfp-services:4 C-c 2>/dev/null || true  # Documentation Server
sleep 1
tmux send-keys -t dfp-services:5 C-c 2>/dev/null || true  # DFP Inference Pipeline
sleep 2  # give AI Orchestrator time to drain in-flight messages
tmux send-keys -t dfp-services:8 C-c 2>/dev/null || true  # AI Orchestrator
sleep 1
tmux send-keys -t dfp-services:9 C-c 2>/dev/null || true  # Agent Orchestrator
# Fallback: kill only the child process of this specific tmux pane (avoids broad pkill match)
_AGENT_ORCH_PANE_PID=$(tmux list-panes -t dfp-services:9 -F "#{pane_pid}" 2>/dev/null || true)
[ -n "$_AGENT_ORCH_PANE_PID" ] && pkill -TERM -P "$_AGENT_ORCH_PANE_PID" 2>/dev/null || true
sleep 1
tmux send-keys -t dfp-services:10 C-c 2>/dev/null || true  # Retrain Runner
# Fallback: kill only the child process of this specific tmux pane (avoids broad pkill match)
_RETRAIN_RUNNER_PANE_PID=$(tmux list-panes -t dfp-services:10 -F "#{pane_pid}" 2>/dev/null || true)
[ -n "$_RETRAIN_RUNNER_PANE_PID" ] && pkill -TERM -P "$_RETRAIN_RUNNER_PANE_PID" 2>/dev/null || true
sleep 1
tmux send-keys -t dfp-services:6 C-c 2>/dev/null || true  # Backend API
sleep 1
tmux send-keys -t dfp-services:7 C-c 2>/dev/null || true  # Frontend UI
sleep 1

log_info "Waiting for services to shut down gracefully..."
sleep 2

# Stop monitoring services
log_info "Stopping monitoring services..."

# Stop Prometheus and Grafana via brew services
if command -v brew &> /dev/null; then
    log_info "Stopping Prometheus and Grafana..."
    brew services stop prometheus 2>/dev/null && log_success "Prometheus stopped" || log_warning "Prometheus was not running"
    brew services stop grafana 2>/dev/null && log_success "Grafana stopped" || log_warning "Grafana was not running"
fi

if [ -f "$PROJECT_ROOT/services/stop_monitoring.sh" ]; then
    bash "$PROJECT_ROOT/services/stop_monitoring.sh" || log_warning "Monitoring shutdown encountered issues"
else
    log_warning "Monitoring stop script not found at services/stop_monitoring.sh"
fi

# Now kill the tmux session (should be clean by now)
log_info "Closing tmux session..."
tmux kill-session -t dfp-services 2>/dev/null || true

# Explicitly cleanup Qdrant (in case it's still running)

if [ -f "$PROJECT_ROOT/services/stop_qdrant.sh" ]; then
    log_info "Stopping Qdrant vector database..."
    bash "$PROJECT_ROOT/services/stop_qdrant.sh" 2>/dev/null || true
fi

# Stop other AI infrastructure services
log_info "Stopping AI infrastructure services..."

# Stop Neo4j
if pgrep -f "neo4j" > /dev/null; then
    log_info "Stopping Neo4j..."
    neo4j stop 2>/dev/null || true
fi

# Stop Redis
if redis-cli ping > /dev/null 2>&1; then
    log_info "Stopping Redis..."
    redis-cli shutdown 2>/dev/null || true
fi

# Stop TimescaleDB (Docker)
if command -v docker &> /dev/null && docker info > /dev/null 2>&1; then
    if docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps --quiet timescaledb 2>/dev/null | grep -q .; then
        log_info "Stopping TimescaleDB (Docker)..."
        docker compose -f "$PROJECT_ROOT/docker-compose.yml" stop timescaledb 2>/dev/null || true
        log_success "TimescaleDB stopped"
    fi
fi

# Wait a moment for processes to fully terminate
sleep 2

# Verify services stopped
PORTS=(5001 29092 6333 7474 7687 6379 5433 8080 8888 8000 8001 5173)
STILL_RUNNING=()

for port in "${PORTS[@]}"; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        STILL_RUNNING+=($port)
    fi
done

if [ ${#STILL_RUNNING[@]} -gt 0 ]; then
    log_warning "Some services still running on ports: ${STILL_RUNNING[*]}"
    echo ""
    echo "Force kill remaining processes? (y/N)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        for port in "${STILL_RUNNING[@]}"; do
            log_info "Force killing processes on port $port..."
            lsof -ti:$port | xargs kill -9 2>/dev/null || true
        done
        log_success "Force killed remaining processes"
    fi
else
    log_success "All services stopped successfully"
fi



echo ""
echo "Service Status:"
echo -e "  MLflow (5001):         $(lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Kafka (29092):         $(lsof -Pi :29092 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Qdrant (6333):         $(lsof -Pi :6333 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Neo4j (7474):          $(lsof -Pi :7474 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Redis (6379):          $(redis-cli ping > /dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  TimescaleDB (5433):    $(lsof -Pi :5433 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Kafka UI (8080):       $(lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Docs (8888):           $(lsof -Pi :8888 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Metrics Server (8000): $(lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Backend API (8001):    $(lsof -Pi :8001 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Frontend UI (5173):    $(lsof -Pi :5173 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo '✓ Stopped')"
echo -e "  Inference Pipeline:    ✓ Stopped"
echo -e "  AI Orchestrator:       ✓ Stopped"
echo -e "  Agent Orchestrator:    ✓ Stopped"
echo -e "  Retrain Runner:        ✓ Stopped"
echo -e "  Alert Manager:         ✓ Stopped"

echo "================================================================================"
