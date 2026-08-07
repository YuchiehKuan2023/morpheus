#!/usr/bin/env bash
#
# DFP Monitoring Service Manager
#
# Manages Prometheus metrics server and alert monitoring for DFP pipeline.
#
# Usage:
#   ./start_monitoring.sh    # Start monitoring services (standalone)
#   ./stop_monitoring.sh     # Stop monitoring services
#   ./check_monitoring.sh    # Check service status
#
# Note: This script is automatically called by start_services.sh
#       You don't need to run it separately unless you want monitoring only.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=================================="
echo "DFP Monitoring Services - START"
echo "=================================="

# Start Pushgateway for batch job metrics persistence
if lsof -Pi :9091 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${GREEN}✓ Pushgateway already running on port 9091${NC}"
else
    if [ -f "$PROJECT_ROOT/bin/pushgateway" ]; then
        echo -e "${GREEN}✓ Starting Pushgateway on port 9091...${NC}"
        mkdir -p "$PROJECT_ROOT/data/pushgateway"
        nohup "$PROJECT_ROOT/bin/pushgateway" \
            --web.listen-address=":9091" \
            --persistence.file="$PROJECT_ROOT/data/pushgateway/metrics.db" \
            --persistence.interval=5m \
            > "$PROJECT_ROOT/logs/pushgateway.log" 2>&1 &

        PUSHGATEWAY_PID=$!
        echo $PUSHGATEWAY_PID > "$PROJECT_ROOT/logs/pushgateway.pid"
        sleep 2
        if lsof -Pi :9091 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
            echo -e "${GREEN}✓ Pushgateway started successfully${NC}"
            echo "  URL: http://localhost:9091"
        else
            echo -e "${YELLOW}⚠ Pushgateway failed to start${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ Pushgateway binary not found at bin/pushgateway${NC}"
    fi
fi

# Metrics server is started by the pipeline itself (in-process)
echo -e "${GREEN}✓ Metrics server will be started by pipeline${NC}"
echo "  The pipeline starts an HTTP server on port 8000 when it runs"
echo "  Endpoint: http://localhost:8000/metrics"
echo "  Health: http://localhost:8000/health"

# Check and optionally start Prometheus
if lsof -Pi :9090 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${GREEN}✓ Prometheus already running on port 9090${NC}"
    echo "  URL: http://localhost:9090"
else
    if command -v prometheus &> /dev/null; then
        echo -e "${GREEN}✓ Starting Prometheus on port 9090...${NC}"

        # Stop brew-managed Prometheus first (it uses wrong config)
        brew services stop prometheus 2>/dev/null || true
        sleep 1

        # Ensure data directory exists
        mkdir -p "$PROJECT_ROOT/data/prometheus"

        # Start Prometheus directly with project config
        nohup prometheus --config.file="$PROJECT_ROOT/config/prometheus.yml" \
            --storage.tsdb.path="$PROJECT_ROOT/data/prometheus" \
            --web.listen-address=":9090" \
            > "$PROJECT_ROOT/logs/prometheus.log" 2>&1 &

        PROMETHEUS_PID=$!
        echo $PROMETHEUS_PID > "$PROJECT_ROOT/logs/prometheus.pid"
        sleep 2
        if lsof -Pi :9090 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
            echo -e "${GREEN}✓ Prometheus started successfully${NC}"
            echo "  URL: http://localhost:9090"
        else
            echo -e "${YELLOW}⚠ Prometheus failed to start, check logs/prometheus.log${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ Prometheus not installed (optional)${NC}"
        echo "  To install: brew install prometheus"
        echo "  Pipeline monitoring works without it (uses built-in metrics server)"
    fi
fi

# Check and optionally start Grafana
if lsof -Pi :3333 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${GREEN}✓ Grafana already running on port 3333${NC}"
    echo "  URL: http://localhost:3333"
else
    if command -v grafana-server &> /dev/null; then
        echo -e "${GREEN}✓ Starting Grafana on port 3333...${NC}"
        # Start Grafana with brew services for persistence
        brew services start grafana 2>/dev/null || {
            # Fallback: start directly in background
            nohup grafana-server \
                --homepath="/opt/homebrew/opt/grafana/share/grafana" \
                --config="/opt/homebrew/etc/grafana/grafana.ini" \
                > "$PROJECT_ROOT/logs/grafana.log" 2>&1 &
        }
        sleep 3
        if lsof -Pi :3333 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
            echo -e "${GREEN}✓ Grafana started successfully${NC}"
            echo "  URL: http://localhost:3333 (default: admin/admin)"
            echo "  Import dashboard: config/grafana_dashboard.json"
        else
            echo -e "${YELLOW}⚠ Grafana failed to start, check logs/grafana.log${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ Grafana not installed (optional)${NC}"
        echo "  To install: brew install grafana"
        echo "  Dashboard available at config/grafana_dashboard.json"
    fi
fi

echo ""
echo "=================================="
echo "Monitoring Configuration"
echo "=================================="
echo "Alert configuration: config/alerting.yaml"
echo "Grafana dashboard: config/grafana_dashboard.json"
echo "Alert log: logs/alerts.log"
echo ""

# Check alert configuration
if [ -f "$PROJECT_ROOT/config/alerting.yaml" ]; then
    echo -e "${GREEN}✓ Alert configuration found${NC}"

    # Check if environment variables are set
    if [ -z "$SLACK_WEBHOOK_URL" ]; then
        echo -e "${YELLOW}⚠ SLACK_WEBHOOK_URL not set (Slack alerts disabled)${NC}"
    else
        echo -e "${GREEN}✓ SLACK_WEBHOOK_URL configured${NC}"
    fi

    if [ -z "$SMTP_USER" ] || [ -z "$SMTP_PASSWORD" ]; then
        echo -e "${YELLOW}⚠ SMTP credentials not set (Email alerts disabled)${NC}"
    else
        echo -e "${GREEN}✓ SMTP credentials configured${NC}"
    fi
else
    echo -e "${RED}✗ Alert configuration not found: config/alerting.yaml${NC}"
fi

echo ""
echo "=================================="
echo "Monitoring Services Ready"
echo "=================================="
echo "The pipeline will start:"
echo "  • Metrics server: http://localhost:8000/metrics"
echo "  • Alert manager: Active (checks every 30s)"
echo "  • System metrics: CPU, memory, disk, GPU"
echo ""
echo "To view metrics:"
echo "  curl http://localhost:8000/metrics"
echo ""
echo "To check alerts:"
echo "  tail -f logs/alerts.log"
echo ""
echo "Next steps:"
echo "  1. Run training: python pipelines/pipeline.py training --config config/pipeline.yaml --train-msg control_messages/train.json"
echo "  2. View metrics: curl http://localhost:8000/metrics | grep dfp_"
echo "  3. Check Prometheus: http://localhost:9090/targets"
echo "  4. Open Grafana: http://localhost:3333"
echo ""
