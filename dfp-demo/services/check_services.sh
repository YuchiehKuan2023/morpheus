#!/bin/bash

################################################################################
# DFP Services Health Check Script
#
# Checks the status and health of all DFP services
#
# Usage:
#   ./services/check_services.sh
################################################################################

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Configuration
KAFKA_PORT=29092
MLFLOW_PORT=5001
QDRANT_PORT=6333
KAFKA_UI_PORT=8080
BACKEND_API_PORT=8001
FRONTEND_UI_PORT=5173

# AI Infrastructure Ports
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
REDIS_PORT=6379
POSTGRES_PORT=5433
TIMESCALEDB_PORT=5433

check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use (service running)
    else
        return 1  # Port is free (service not running)
    fi
}

get_status_icon() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi
}

echo ""
echo "================================================================================"
echo -e "${BLUE}DFP Services Health Check${NC}"
echo "================================================================================"
echo ""

# Check tmux session
echo -e "${BLUE}[Tmux Session]${NC}"
if tmux has-session -t dfp-services 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Session 'dfp-services' is active"
    echo -e "    Windows:"
    echo -e "      0: MLflow"
    echo -e "      1: Kafka"
    echo -e "      2: Qdrant"
    echo -e "      3: Kafka UI"
    echo -e "      4: Documentation Server"
    echo -e "      5: DFP Inference Pipeline"
    echo -e "      6: Backend API"
    echo -e "      7: Frontend UI"
    echo -e "      8: AI Orchestrator"
    echo -e "      9: AI-Agents (Agent Orchestrator)"
    echo -e "     10: Retrain Runner (DFP + Classifiers)"
    echo -e "    Command: ${BLUE}tmux attach -t dfp-services${NC}"
else
    echo -e "  ${RED}✗${NC} Session 'dfp-services' not found"
    echo -e "    Command: ${BLUE}./services/start_services.sh${NC}"
fi

echo ""
echo -e "${BLUE}[Service Status]${NC}"

# MLflow
echo -n "  MLflow (port $MLFLOW_PORT):       "
if check_port $MLFLOW_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    # Health check
    if curl -f -s http://localhost:$MLFLOW_PORT/health > /dev/null 2>&1; then
        echo -e "    Health: ${GREEN}✓ Healthy${NC}"
        echo -e "    URL: ${BLUE}http://localhost:$MLFLOW_PORT${NC}"
    else
        echo -e "    Health: ${YELLOW}⚠ Starting${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Kafka (KRaft mode - no Zookeeper needed)
echo -n "  Kafka KRaft (port $KAFKA_PORT): "
if check_port $KAFKA_PORT; then
    echo -e "${GREEN}✓ Running${NC}"

    # Check Kafka responsiveness
    if command -v kafka-broker-api-versions &> /dev/null; then
        if kafka-broker-api-versions --bootstrap-server localhost:$KAFKA_PORT > /dev/null 2>&1; then
            echo -e "    Health: ${GREEN}✓ Healthy${NC}"

            # List topics
            echo "    Topics:"
            kafka-topics --list --bootstrap-server localhost:$KAFKA_PORT 2>/dev/null | while read topic; do
                echo "      - $topic"
            done
        else
            echo -e "    Health: ${YELLOW}⚠ Starting${NC}"
        fi
    fi
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Qdrant Vector Database
echo -n "  Qdrant (port $QDRANT_PORT):       "
if check_port $QDRANT_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    # Health check
    if curl -f -s http://localhost:$QDRANT_PORT/healthz > /dev/null 2>&1; then
        echo -e "    Health: ${GREEN}✓ Healthy${NC}"
        echo -e "    API: ${BLUE}http://localhost:$QDRANT_PORT${NC}"
        echo -e "    Dashboard: ${BLUE}http://localhost:$QDRANT_PORT/dashboard${NC}"
        echo -e "    gRPC: localhost:6334"
    else
        echo -e "    Health: ${YELLOW}⚠ Starting${NC}"
    fi
    echo -e "    View logs: ${BLUE}tail -f data/logs/qdrant.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 2"
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Kafka UI (optional)
echo -n "  Kafka UI (port $KAFKA_UI_PORT):    "
if check_port $KAFKA_UI_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    URL: ${BLUE}http://localhost:$KAFKA_UI_PORT${NC}"
else
    echo -e "${YELLOW}○ Not running${NC} (optional - requires Java)"
    echo -e "    Note: Kafka UI needs Java runtime. Install with: ${BLUE}brew install openjdk${NC}"
fi

# DFP Inference Pipeline
echo -n "  DFP Inference Pipeline:        "
if tmux has-session -t dfp-services 2>/dev/null && pgrep -f "pipeline.py inference" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    Mode: Streaming inference"
    echo -e "    Consumer group: morpheus-dfp-inference"
    echo -e "    View logs: ${BLUE}tail -f data/logs/dfp-infer.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 5"
else
    echo -e "${RED}✗ Not running${NC}"
fi

# AI Orchestrator
echo -n "  AI Orchestrator:               "
if pgrep -f "run_ai_orchestrator.py" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    Consuming: dfp-detections, dfp-clean-events"
    echo -e "    View logs: ${BLUE}tail -f data/logs/ai-orchestrator.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 8"
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Agent Orchestrator (Multi-Agent System)
echo -n "  Agent Orchestrator:            "
if pgrep -f "run_agent_orchestrator.py" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    Consuming: dfp-agent-tasks"
    echo -e "    View logs: ${BLUE}tail -f data/logs/agent_orchestrator.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 9"
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Retrain Runner (DFP + Classifier Retraining)
echo -n "  Retrain Runner:                "
if pgrep -f "run_retrain_runner.py" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    Polls: dfp_retrain_jobs (DFP) + classifier thresholds"
    echo -e "    View logs: ${BLUE}tail -f data/logs/retrain_runner.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 10"
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Backend API
echo -n "  Backend API (port $BACKEND_API_PORT):     "
if check_port $BACKEND_API_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    if curl -f -s http://localhost:$BACKEND_API_PORT/api/health > /dev/null 2>&1; then
        echo -e "    Health: ${GREEN}✓ Healthy${NC}"
        echo -e "    URL: ${BLUE}http://localhost:$BACKEND_API_PORT${NC}"
        echo -e "    Docs: ${BLUE}http://localhost:$BACKEND_API_PORT/docs${NC}"
    else
        echo -e "    Health: ${YELLOW}⚠ Starting${NC}"
    fi
    echo -e "    View logs: ${BLUE}tail -f data/logs/backend-api.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 6"
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Frontend UI
echo -n "  Frontend UI (port $FRONTEND_UI_PORT):     "
if check_port $FRONTEND_UI_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    URL: ${BLUE}http://localhost:$FRONTEND_UI_PORT${NC}"
    echo -e "    View logs: ${BLUE}tail -f data/logs/frontend-ui.log${NC}"
    echo -e "    Attach: ${BLUE}tmux attach -t dfp-services${NC} then Ctrl+B, 7"
else
    echo -e "${RED}✗ Not running${NC}"
fi

echo ""
echo -e "${BLUE}[AI Infrastructure Services]${NC}"

# Neo4j Knowledge Graph
echo -n "  Neo4j (HTTP: $NEO4J_HTTP_PORT, Bolt: $NEO4J_BOLT_PORT): "
if check_port $NEO4J_HTTP_PORT && check_port $NEO4J_BOLT_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    # Check Neo4j status
    if neo4j status 2>&1 | grep -q "Neo4j is running"; then
        NEO4J_PID=$(neo4j status 2>&1 | sed -n 's/.*pid:\([0-9]*\).*/\1/p' | head -1)
        [ -z "$NEO4J_PID" ] && NEO4J_PID="?"
        echo -e "    Health: ${GREEN}✓ Healthy${NC} (PID: $NEO4J_PID)"
        echo -e "    Browser: ${BLUE}http://localhost:$NEO4J_HTTP_PORT${NC}"
        echo -e "    Bolt: bolt://localhost:$NEO4J_BOLT_PORT"
        echo -e "    Credentials: neo4j/dfp-ai-2026"
    else
        echo -e "    Health: ${YELLOW}⚠ Starting${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
    echo -e "    Start: ${BLUE}neo4j start${NC}"
fi

# Redis Cache
echo -n "  Redis (port $REDIS_PORT):                  "
if check_port $REDIS_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    # Check Redis responsiveness
    if redis-cli ping > /dev/null 2>&1; then
        echo -e "    Health: ${GREEN}✓ Healthy${NC} (PONG)"
        # Check persistence mode
        AOF_STATUS=$(redis-cli config get appendonly 2>/dev/null | tail -1)
        if [ "$AOF_STATUS" = "yes" ]; then
            echo -e "    Persistence: ${GREEN}✓ AOF Enabled${NC}"
        else
            echo -e "    Persistence: ${YELLOW}⚠ AOF Disabled${NC}"
        fi
        echo -e "    Data: data/redis/"
    else
        echo -e "    Health: ${YELLOW}⚠ Not responding${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
    echo -e "    Start: ${BLUE}redis-server --dir ./data/redis --appendonly yes --daemonize yes${NC}"
fi

# TimescaleDB (Docker — time-series analytics)
echo -n "  TimescaleDB (port $TIMESCALEDB_PORT):      "
if check_port $TIMESCALEDB_PORT; then
    echo -e "${GREEN}✓ Running${NC}"
    if psql -h localhost -p $TIMESCALEDB_PORT -U dfp_ai -d dfp_ai \
            -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';" \
            -t > /dev/null 2>&1; then
        TSDB_VER=$(psql -h localhost -p $TIMESCALEDB_PORT -U dfp_ai -d dfp_ai \
            -t -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';" \
            2>/dev/null | tr -d '[:space:]')
        HT_COUNT=$(psql -h localhost -p $TIMESCALEDB_PORT -U dfp_ai -d dfp_ai \
            -t -c "SELECT count(*) FROM timescaledb_information.hypertables;" \
            2>/dev/null | tr -d '[:space:]')
        CA_COUNT=$(psql -h localhost -p $TIMESCALEDB_PORT -U dfp_ai -d dfp_ai \
            -t -c "SELECT count(*) FROM timescaledb_information.continuous_aggregates;" \
            2>/dev/null | tr -d '[:space:]')
        echo -e "    Health: ${GREEN}✓ Healthy${NC} (TimescaleDB v$TSDB_VER)"
        echo -e "    Hypertables: $HT_COUNT  Continuous aggregates: $CA_COUNT"
        echo -e "    Port: $TIMESCALEDB_PORT (Docker container)"
    else
        echo -e "    Health: ${YELLOW}⚠ Port open but TimescaleDB extension not responding${NC}"
    fi
else
    echo -e "${YELLOW}○ Not running${NC}"
    echo -e "    Start: ${BLUE}docker compose up -d timescaledb${NC}"
fi

echo ""
echo -e "${BLUE}[Monitoring Services]${NC}"

# Metrics Server
echo -n "  Metrics Server (port 8000):    "
if check_port 8000; then
    echo -e "${GREEN}✓ Running${NC}"
    if curl -f -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "    Health: ${GREEN}✓ Healthy${NC}"
        echo -e "    Metrics: ${BLUE}http://localhost:8000/metrics${NC}"
        echo -e "    Health: ${BLUE}http://localhost:8000/health${NC}"
    else
        echo -e "    Health: ${YELLOW}⚠ Starting${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Alert Manager
echo -n "  Alert Manager:                 "
if pgrep -f "alerting_utils" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Running${NC}"
    if [ -f "$PROJECT_ROOT/logs/alerts.log" ]; then
        alert_count=$(wc -l < "$PROJECT_ROOT/logs/alerts.log" 2>/dev/null || echo 0)
        echo -e "    Alerts logged: $alert_count"
        echo -e "    View: ${BLUE}tail -f logs/alerts.log${NC}"
    fi
else
    echo -e "${YELLOW}○ Not running${NC} (starts with pipeline)"
fi

# Prometheus (optional)
echo -n "  Prometheus (port 9090):        "
if check_port 9090; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    URL: ${BLUE}http://localhost:9090${NC}"
else
    echo -e "${YELLOW}○ Not running${NC} (optional)"
    echo -e "    Start: ${BLUE}brew services start prometheus${NC}"
fi

# Grafana (optional)
echo -n "  Grafana (port 3000):           "
if check_port 3000; then
    echo -e "${GREEN}✓ Running${NC}"
    echo -e "    URL: ${BLUE}http://localhost:3000${NC}"
else
    echo -e "${YELLOW}○ Not running${NC} (optional)"
    echo -e "    Start: ${BLUE}brew services start grafana${NC}"
fi

echo ""
echo -e "${BLUE}[Monitoring Configuration]${NC}"

# Check monitoring config files
if [ -f "$PROJECT_ROOT/config/alerting.yaml" ]; then
    rule_count=$(grep -c "name:" "$PROJECT_ROOT/config/alerting.yaml" 2>/dev/null || echo 0)
    echo -e "  ${GREEN}✓${NC} alerting.yaml ($rule_count rules)"
else
    echo -e "  ${RED}✗${NC} alerting.yaml (missing)"
fi

if [ -f "$PROJECT_ROOT/config/prometheus.yml" ]; then
    echo -e "  ${GREEN}✓${NC} prometheus.yml"
else
    echo -e "  ${YELLOW}○${NC} prometheus.yml (missing - optional)"
fi

if [ -f "$PROJECT_ROOT/config/grafana_dashboard.json" ]; then
    echo -e "  ${GREEN}✓${NC} grafana_dashboard.json"
else
    echo -e "  ${YELLOW}○${NC} grafana_dashboard.json (missing - optional)"
fi

echo ""
echo -e "${BLUE}[Data Directories]${NC}"

# Check directories
DIRS=(
    "data/mlflow"
    "data/logs"
    "data/kafka"
    "data/kafka-logs"
    "data/input"
    "data/output/detections"
    "data/output/profiles"
)

for dir in "${DIRS[@]}"; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        size=$(du -sh "$PROJECT_ROOT/$dir" 2>/dev/null | cut -f1)
        echo -e "  ${GREEN}✓${NC} $dir ($size)"
    else
        echo -e "  ${RED}✗${NC} $dir (missing)"
    fi
done

echo ""
echo -e "${BLUE}[Log Files]${NC}"

# Check log files
LOGS=(
    "data/logs/mlflow.log"
    "data/logs/kafka.log"
    "data/logs/kafka-ui.log"
    "data/logs/dfp-infer.log"
    "data/logs/ai-orchestrator.log"
    "data/logs/agent_orchestrator.log"
    "data/logs/retrain_runner.log"
    "data/logs/backend-api.log"
    "data/logs/frontend-ui.log"
)

for log in "${LOGS[@]}"; do
    if [ -f "$PROJECT_ROOT/$log" ]; then
        size=$(du -sh "$PROJECT_ROOT/$log" 2>/dev/null | cut -f1)
        lines=$(wc -l < "$PROJECT_ROOT/$log")
        echo -e "  ${GREEN}✓${NC} $log ($size, $lines lines)"
    else
        echo -e "  ${YELLOW}○${NC} $log (not created)"
    fi
done

echo ""
echo -e "${BLUE}[MLflow Models]${NC}"

if check_port $MLFLOW_PORT; then
    # Try to get registered models count
    model_count=$(curl -s http://localhost:$MLFLOW_PORT/api/2.0/mlflow/registered-models/search 2>/dev/null | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('registered_models', [])))" 2>/dev/null || echo "?")
    echo "  Registered models: $model_count"
    echo -e "  View models: ${BLUE}http://localhost:$MLFLOW_PORT/#/models${NC}"
else
    echo -e "  ${YELLOW}Cannot check models (MLflow not running)${NC}"
fi

echo ""
echo -e "${BLUE}[Quick Test Commands]${NC}"
echo -e "  Test MLflow:   ${BLUE}curl http://localhost:$MLFLOW_PORT/health${NC}"
echo -e "  List topics:   ${BLUE}kafka-topics --list --bootstrap-server localhost:$KAFKA_PORT${NC}"
echo -e "  Test produce:  ${BLUE}echo 'test' | kafka-console-producer --bootstrap-server localhost:$KAFKA_PORT --topic test${NC}"
echo -e "  Test consume:  ${BLUE}kafka-console-consumer --bootstrap-server localhost:$KAFKA_PORT --topic test --from-beginning --max-messages 1${NC}"
echo ""
echo "================================================================================"
