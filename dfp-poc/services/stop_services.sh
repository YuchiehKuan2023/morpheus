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
tmux send-keys -t dfp-services:2 C-c 2>/dev/null || true  # Kafka UI
sleep 1
tmux send-keys -t dfp-services:3 C-c 2>/dev/null || true  # Documentation Server
sleep 1
tmux send-keys -t dfp-services:4 C-c 2>/dev/null || true  # DFP Inference Pipeline
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

# Wait a moment for processes to fully terminate
sleep 2

# Verify services stopped
PORTS=(5001 29092 8080 8888 8000)  # Added 8888 for documentation, 8000 for metrics server
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

# Get PROJECT_ROOT for monitoring check
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"

echo ""
echo "Service Status:"
echo -e "  MLflow (5001):     $(lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo ' ✓ Stopped')"
echo -e "  Kafka (29092):     $(lsof -Pi :29092 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo ' ✓ Stopped')"
echo -e "  Kafka UI (8080):   $(lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo ' ✓ Stopped')"
echo -e "  Docs (8888):       $(lsof -Pi :8888 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo ' ✓ Stopped')"
echo -e "  Metrics (8000):    $(lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 && echo '❌ Still running' || echo ' ✓ Stopped')"
echo -e "  Inference Pipeline: ✓ Stopped"
echo -e "  Alert Manager:      ✓ Stopped"

echo "================================================================================"
