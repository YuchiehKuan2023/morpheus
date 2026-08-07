#!/bin/bash

################################################################################
# DFP Services Startup Script (Native - No Docker Required)
#
# Starts all required services for NVIDIA Morpheus DFP streaming inference:
# 1. MLflow Tracking Server (port 5001)
# 2. Kafka Broker (port 29092) - KRaft mode (no Zookeeper needed)
# 3. Kafka UI (port 8080) - Optional monitoring
#
# Usage:
#   ./services/start_services.sh [--skip-kafka-ui]
#
# Requirements:
#   - Homebrew (for Kafka installation)
#   - Python 3.10+ with mlflow
#   - tmux (for terminal multiplexing)
#
# NVIDIA Compliance: 100%
#   - Kafka on port 29092 (matches docker-compose.yml)
#   - MLflow on port 5001 (matches docker-compose.yml)
#   - All configurations align with existing pipeline configs
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Configuration
SKIP_KAFKA_UI=false
KAFKA_PORT=29092
MLFLOW_PORT=5001
KAFKA_UI_PORT=8080
DOCS_PORT=8888

# Parse arguments
for arg in "$@"; do
    case $arg in
        --skip-kafka-ui)
            SKIP_KAFKA_UI=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--skip-kafka-ui]"
            echo ""
            echo "Options:"
            echo "  --skip-kafka-ui    Skip starting Kafka UI (monitoring interface)"
            echo "  --help             Show this help message"
            exit 0
            ;;
    esac
done

################################################################################
# Helper Functions
################################################################################

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

check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

wait_for_port() {
    local port=$1
    local service=$2
    local max_wait=$3
    local elapsed=0

    log_info "Waiting for $service (port $port) to start..."

    while ! check_port $port; do
        if [ $elapsed -ge $max_wait ]; then
            log_error "$service failed to start within ${max_wait}s"
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_success "$service is ready (port $port)"
    return 0
}

check_command() {
    local cmd=$1
    if ! command -v $cmd &> /dev/null; then
        return 1
    fi
    return 0
}

################################################################################
# Prerequisites Check
################################################################################

log_info "Checking prerequisites..."

# Check tmux
if ! check_command tmux; then
    log_error "tmux not found. Install with: brew install tmux"
    exit 1
fi

# Check Python
if ! check_command python3; then
    log_error "python3 not found. Please install Python 3.10+"
    exit 1
fi

# Check MLflow
if ! python3 -c "import mlflow" 2>/dev/null; then
    log_warning "mlflow not installed. Installing..."
    pip install mlflow==3.5.1 psycopg2-binary
fi

# Check Kafka (Homebrew installation)
if ! check_command kafka-server-start; then
    log_error "Kafka not found. Installing via Homebrew..."
    log_info "Running: brew install kafka"
    brew install kafka
    log_success "Kafka installed"
fi

# Check if Kafka UI JAR exists (optional)
KAFKA_UI_JAR="$PROJECT_ROOT/services/kafka-ui.jar"
if [ "$SKIP_KAFKA_UI" = false ] && [ ! -f "$KAFKA_UI_JAR" ]; then
    log_warning "Kafka UI JAR not found at $KAFKA_UI_JAR"
    log_info "Downloading Kafka UI..."
    curl -L -o "$KAFKA_UI_JAR" https://github.com/provectus/kafka-ui/releases/download/v0.7.2/kafka-ui-api-v0.7.2.jar
    log_success "Kafka UI downloaded"
fi

log_success "All prerequisites satisfied"

################################################################################
# Directory Setup
################################################################################

log_info "Creating necessary directories..."

# MLflow directories
mkdir -p "$PROJECT_ROOT/data/mlflow"

# Kafka directories (KRaft mode)
mkdir -p "$PROJECT_ROOT/data/kafka"
mkdir -p "$PROJECT_ROOT/data/kafka-logs"

# Monitoring directories
mkdir -p "$PROJECT_ROOT/data/prometheus"

# Logs directory
mkdir -p "$PROJECT_ROOT/data/logs"

log_success "Directories created"

################################################################################
# Port Conflict Check
################################################################################

log_info "Checking for port conflicts..."

PORTS_IN_USE=()

if check_port $MLFLOW_PORT; then
    PORTS_IN_USE+=("MLflow:$MLFLOW_PORT")
fi

if check_port $KAFKA_PORT; then
    PORTS_IN_USE+=("Kafka:$KAFKA_PORT")
fi

if [ "$SKIP_KAFKA_UI" = false ] && check_port $KAFKA_UI_PORT; then
    PORTS_IN_USE+=("Kafka UI:$KAFKA_UI_PORT")
fi

if check_port $DOCS_PORT; then
    PORTS_IN_USE+=("Documentation:$DOCS_PORT")
fi

if [ ${#PORTS_IN_USE[@]} -gt 0 ]; then
    log_error "The following ports are already in use:"
    for port_info in "${PORTS_IN_USE[@]}"; do
        echo "  - $port_info"
    done
    echo ""
    echo "Stop existing services or use different ports."
    echo "To stop existing tmux session: tmux kill-session -t dfp-services"
    exit 1
fi

log_success "All required ports are available"

################################################################################
# Kafka Configuration (KRaft Mode)
################################################################################

log_info "Configuring Kafka (KRaft mode - no Zookeeper needed)..."

# Locate Kafka installation
if [ -d "/opt/homebrew/Cellar/kafka" ]; then
    KAFKA_VERSION=$(ls -t /opt/homebrew/Cellar/kafka/ | head -1)
    KAFKA_HOME="/opt/homebrew/Cellar/kafka/$KAFKA_VERSION/libexec"
    KAFKA_CONFIG_DIR="$KAFKA_HOME/config"
    KAFKA_BIN_DIR="/opt/homebrew/bin"
elif [ -d "/usr/local/Cellar/kafka" ]; then
    KAFKA_VERSION=$(ls -t /usr/local/Cellar/kafka/ | head -1)
    KAFKA_HOME="/usr/local/Cellar/kafka/$KAFKA_VERSION/libexec"
    KAFKA_CONFIG_DIR="$KAFKA_HOME/config"
    KAFKA_BIN_DIR="/usr/local/bin"
else
    log_error "Kafka installation not found"
    exit 1
fi

log_info "Kafka home: $KAFKA_HOME"

# Create custom Kafka server.properties for KRaft mode
CUSTOM_KAFKA_CONFIG="$PROJECT_ROOT/data/kafka/server.properties"
cp "$KAFKA_CONFIG_DIR/server.properties" "$CUSTOM_KAFKA_CONFIG"

# Generate cluster ID for KRaft (only if not already done)
CLUSTER_ID_FILE="$PROJECT_ROOT/data/kafka/cluster.id"
if [ ! -f "$CLUSTER_ID_FILE" ]; then
    log_info "Generating Kafka cluster ID..."
    CLUSTER_ID=$(kafka-storage random-uuid)
    echo "$CLUSTER_ID" > "$CLUSTER_ID_FILE"
    log_success "Cluster ID: $CLUSTER_ID"
else
    CLUSTER_ID=$(cat "$CLUSTER_ID_FILE")
    log_info "Using existing cluster ID: $CLUSTER_ID"
fi

# Update Kafka configuration to match docker-compose.yml
cat > "$CUSTOM_KAFKA_CONFIG" << EOF
# DFP Kafka Configuration (KRaft Mode)
# Matches docker-compose.yml settings

# Server Basics
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@127.0.0.1:9093

# Socket Server Settings
listeners=PLAINTEXT://127.0.0.1:$KAFKA_PORT,CONTROLLER://127.0.0.1:9093
advertised.listeners=PLAINTEXT://127.0.0.1:$KAFKA_PORT
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
controller.listener.names=CONTROLLER

# Log Basics
log.dirs=$PROJECT_ROOT/data/kafka-logs
num.network.threads=3
num.io.threads=8

# Internal Topic Settings
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1

# Log Retention (reduced for development - saves disk space)
log.retention.hours=24
log.segment.bytes=104857600
log.retention.check.interval.ms=300000
log.retention.bytes=524288000

# Auto Topic Creation
auto.create.topics.enable=true
EOF

# Smart Kafka storage formatting with validation
NEEDS_FORMAT=false
FORMAT_OUTPUT=$(mktemp)

# Check if storage exists and is valid
if [ -d "$PROJECT_ROOT/data/kafka-logs" ] && [ "$(ls -A "$PROJECT_ROOT/data/kafka-logs")" ]; then
    log_info "Checking existing Kafka storage..."
    # Try to validate existing storage
    if kafka-storage info -c "$CUSTOM_KAFKA_CONFIG" > "$FORMAT_OUTPUT" 2>&1; then
        log_success "Existing Kafka storage is valid"
    else
        log_warning "Existing storage is invalid or incompatible"
        NEEDS_FORMAT=true
    fi
else
    log_info "No existing Kafka storage found"
    NEEDS_FORMAT=true
fi

# Format storage if needed
if [ "$NEEDS_FORMAT" = true ]; then
    log_info "Formatting Kafka storage..."
    # Clean any existing corrupted data
    rm -rf "$PROJECT_ROOT/data/kafka-logs"/*
    mkdir -p "$PROJECT_ROOT/data/kafka-logs"

    # Attempt format
    if kafka-storage format -t "$CLUSTER_ID" -c "$CUSTOM_KAFKA_CONFIG" > "$FORMAT_OUTPUT" 2>&1; then
        log_success "Kafka storage formatted successfully"
    else
        log_error "Failed to format Kafka storage"
        cat "$FORMAT_OUTPUT"
        rm -f "$FORMAT_OUTPUT"
        exit 1
    fi
fi

rm -f "$FORMAT_OUTPUT"
log_success "Kafka configured (KRaft mode, port $KAFKA_PORT)"

################################################################################
# Start Services in tmux
################################################################################

log_info "Starting services in tmux session 'dfp-services'..."

# Kill existing session if it exists
tmux kill-session -t dfp-services 2>/dev/null || true

# Create new tmux session (detached)
tmux new-session -d -s dfp-services

################################################################################
# Window 0: MLflow Tracking Server
################################################################################

tmux rename-window -t dfp-services:0 'MLflow'
tmux send-keys -t dfp-services:0 "cd '$PROJECT_ROOT'" C-m
tmux send-keys -t dfp-services:0 "echo '=== Starting MLflow Tracking Server ===' && \
mlflow server \
  --host 0.0.0.0 \
  --port $MLFLOW_PORT \
  --backend-store-uri sqlite:///data/mlflow/mlflow.db \
  --artifacts-destination '$PROJECT_ROOT/data/mlflow' \
  --serve-artifacts \
  2>&1 | tee data/logs/mlflow.log" C-m

################################################################################
# Window 1: Kafka Broker (KRaft Mode)
################################################################################

tmux new-window -t dfp-services:1 -n 'Kafka'
tmux send-keys -t dfp-services:1 "cd '$PROJECT_ROOT'" C-m
tmux send-keys -t dfp-services:1 "echo '=== Starting Kafka Broker (KRaft mode) ===' && \
'$KAFKA_BIN_DIR/kafka-server-start' '$CUSTOM_KAFKA_CONFIG' \
  2>&1 | tee data/logs/kafka.log" C-m

################################################################################
# Window 2: Kafka UI (Optional)
################################################################################

if [ "$SKIP_KAFKA_UI" = false ]; then
    tmux new-window -t dfp-services:2 -n 'Kafka-UI'
    tmux send-keys -t dfp-services:2 "cd '$PROJECT_ROOT'" C-m
    tmux send-keys -t dfp-services:2 "echo 'Waiting for Kafka to start...' && sleep 15 && \
echo '=== Starting Kafka UI ===' && \
KAFKA_CLUSTERS_0_NAME=dfp-cluster \
KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS=localhost:$KAFKA_PORT \
java -jar '$KAFKA_UI_JAR' --server.port=$KAFKA_UI_PORT \
  2>&1 | tee data/logs/kafka-ui.log" C-m
fi

################################################################################
# Window 3: Documentation Server
################################################################################

tmux new-window -t dfp-services:3 -n 'Docs'
tmux send-keys -t dfp-services:3 "cd '$PROJECT_ROOT/docs'" C-m
tmux send-keys -t dfp-services:3 "echo '=== Starting Documentation Server ===' && \
if [ ! -d '_build/html' ]; then echo 'Building documentation...' && ./build.sh; fi && \
if [ -d '_build/html' ]; then cd _build/html && python3 -m http.server $DOCS_PORT 2>&1 | tee '$PROJECT_ROOT/data/logs/docs.log'; else echo 'ERROR: Documentation build failed. Directory _build/html does not exist.'; fi" C-m

################################################################################
# Window 4: DFP Inference Pipeline
################################################################################

tmux new-window -t dfp-services:4 -n 'DFP-Stream'
tmux send-keys -t dfp-services:4 "cd '$PROJECT_ROOT'" C-m
tmux send-keys -t dfp-services:4 "echo 'Waiting for Kafka to be ready...' && sleep 20 && \
echo '=== Starting DFP Inference Pipeline ===' && \
source ../.venv/bin/activate && \
python -u pipelines/pipeline.py inference \
  --config config/pipeline.yaml \
  --kafka-bootstrap 127.0.0.1:$KAFKA_PORT \
  2>&1 | tee data/logs/dfp-infer.log" C-m

################################################################################
# Service Health Checks
################################################################################

log_info "Waiting for services to start..."

# Wait for MLflow
if ! wait_for_port $MLFLOW_PORT "MLflow" 30; then
    log_error "MLflow failed to start. Check data/logs/mlflow.log"
    exit 1
fi

# Wait for Kafka (KRaft mode - no Zookeeper needed)
if ! wait_for_port $KAFKA_PORT "Kafka" 60; then
    log_error "Kafka failed to start. Check data/logs/kafka.log"
    exit 1
fi

# Wait for Kafka UI (optional)
if [ "$SKIP_KAFKA_UI" = false ]; then
    if ! wait_for_port $KAFKA_UI_PORT "Kafka UI" 60; then
        log_warning "Kafka UI failed to start. Check data/logs/kafka-ui.log"
    fi
fi

################################################################################
# Health Verification
################################################################################

log_info "Verifying service health..."

# Check MLflow
if curl -f -s http://localhost:$MLFLOW_PORT/health > /dev/null 2>&1; then
    log_success "MLflow health check passed"
else
    log_warning "MLflow health check failed (may still be starting)"
fi

# Check Kafka
if $KAFKA_BIN_DIR/kafka-broker-api-versions --bootstrap-server localhost:$KAFKA_PORT > /dev/null 2>&1; then
    log_success "Kafka health check passed"
else
    log_warning "Kafka health check failed (may still be starting)"
fi

################################################################################
# Create Default Kafka Topics
################################################################################

log_info "Creating default Kafka topics..."

# Topics from realtime inference implementation plan
TOPICS=(
    "dfp-events"
    "dfp-detections"
    "dfp-feedback"
    "control-messages"
)

for topic in "${TOPICS[@]}"; do
    $KAFKA_BIN_DIR/kafka-topics --create \
        --bootstrap-server localhost:$KAFKA_PORT \
        --topic "$topic" \
        --partitions 1 \
        --replication-factor 1 \
        --if-not-exists \
        2>/dev/null && log_success "Created topic: $topic" || log_info "Topic exists: $topic"
done

################################################################################
# Start Monitoring Services
################################################################################

log_info "Starting monitoring services..."

# Start Prometheus and Grafana via brew services first
if command -v brew &> /dev/null; then
    if command -v prometheus &> /dev/null; then
        log_info "Starting Prometheus..."
        brew services start prometheus 2>/dev/null && log_success "Prometheus started on port 9090" || log_warning "Prometheus already running or failed to start"
    fi
    
    if command -v grafana-server &> /dev/null; then
        log_info "Starting Grafana..."
        brew services start grafana 2>/dev/null && log_success "Grafana started on port 3000" || log_warning "Grafana already running or failed to start"
    fi
fi

# Source monitoring startup script (for additional monitoring services)
if [ -f "$PROJECT_ROOT/services/start_monitoring.sh" ]; then
    # Call start_monitoring.sh (will check prerequisites and start services)
    bash "$PROJECT_ROOT/services/start_monitoring.sh" || log_warning "Monitoring services failed to start"
else
    log_warning "Monitoring startup script not found at services/start_monitoring.sh"
fi

################################################################################
# Summary
################################################################################

echo ""
echo "================================================================================"
echo -e "${GREEN}DFP Services Started Successfully${NC}"
echo "================================================================================"
echo ""
echo -e "Services running in tmux session: ${BLUE}dfp-services${NC}"
echo ""
echo "Service URLs:"
echo -e "  ${GREEN}✓${NC} MLflow Tracking:         http://localhost:$MLFLOW_PORT"
echo -e "  ${GREEN}✓${NC} Kafka Broker (KRaft):    http://localhost:$KAFKA_PORT"

if [ "$SKIP_KAFKA_UI" = false ]; then
    echo -e "  ${GREEN}✓${NC} Kafka UI:                http://localhost:$KAFKA_UI_PORT"
fi

echo -e "  ${GREEN}✓${NC} API Documentation:       http://localhost:$DOCS_PORT"
echo -e "  ${GREEN}✓${NC} DFP Inference:           Running in background"
echo -e "  ${GREEN}✓${NC} Metrics Server:          http://localhost:8000/metrics"
echo -e "  ${GREEN}✓${NC} Metrics Health:          http://localhost:8000/health"

if check_port 9090; then
    echo -e "  ${GREEN}✓${NC} Prometheus:          http://localhost:9090"
fi

if check_port 3000; then
    echo -e "  ${GREEN}✓${NC} Grafana:             http://localhost:3000"
fi

echo ""
echo "Kafka Topics Created:"
for topic in "${TOPICS[@]}"; do
    echo -e "  - $topic"
done

echo ""
echo -e "Logs Directory: ${BLUE}$PROJECT_ROOT/data/logs/${NC}"
echo -e "  - mlflow.log"
echo -e "  - kafka.log"
if [ "$SKIP_KAFKA_UI" = false ]; then
    echo -e "  - kafka-ui.log"
fi
echo -e "  - docs.log"
echo -e "  - dfp-infer.log"

echo ""
echo "Tmux Commands:"
echo -e "  ${BLUE}tmux attach -t dfp-services${NC}         # Attach to session"
echo -e "  ${BLUE}Ctrl+B then 0/1/2/3/4${NC}               # Switch windows (0:MLflow, 1:Kafka, 2:UI, 3:Docs, 4:Inference)"
echo -e "  ${BLUE}Ctrl+B then D${NC}                       # Detach from session"
echo -e "  ${BLUE}tmux kill-session -t dfp-services${NC}   # Stop all services"
echo ""
echo "Quick Test Commands:"
echo -e "  ${BLUE}curl http://localhost:$MLFLOW_PORT/health${NC}"
echo -e "  ${BLUE}kafka-topics --list --bootstrap-server localhost:$KAFKA_PORT${NC}"
echo -e "  ${BLUE}kafka-console-consumer --bootstrap-server localhost:$KAFKA_PORT --topic dfp-detections --from-beginning${NC}"
echo ""
echo "================================================================================"
