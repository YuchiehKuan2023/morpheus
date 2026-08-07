#!/usr/bin/env bash
#
# DFP Monitoring Service Status Checker
#
# Checks the status of all monitoring components.
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=================================="
echo "DFP Monitoring Status"
echo "=================================="

# Function to check if port is open
check_port() {
    local port=$1
    local service=$2

    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo -e "${GREEN}✓ $service (port $port): RUNNING${NC}"
        return 0
    else
        echo -e "${RED}✗ $service (port $port): NOT RUNNING${NC}"
        return 1
    fi
}

# Function to check HTTP endpoint
check_endpoint() {
    local url=$1
    local service=$2

    if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200" ; then
        echo -e "${GREEN}✓ $service: RESPONDING${NC}"
        return 0
    else
        echo -e "${RED}✗ $service: NOT RESPONDING${NC}"
        return 1
    fi
}

echo "Services:"
echo ""

# Check metrics server
check_port 8000 "Metrics Server"
if [ $? -eq 0 ]; then
    check_endpoint "http://localhost:8000/health" "Health Check"
    check_endpoint "http://localhost:8000/metrics" "Metrics Endpoint"
fi

echo ""

# Check Prometheus
check_port 9090 "Prometheus"
if [ $? -eq 0 ]; then
    check_endpoint "http://localhost:9090/-/healthy" "Prometheus Health"
fi

echo ""

# Check Grafana
check_port 3000 "Grafana"
if [ $? -eq 0 ]; then
    check_endpoint "http://localhost:3000/api/health" "Grafana Health"
fi

echo ""
echo "=================================="
echo "Configuration Files:"
echo "=================================="

# Check configuration files
if [ -f "config/alerting.yaml" ]; then
    echo -e "${GREEN}✓ config/alerting.yaml${NC}"
else
    echo -e "${RED}✗ config/alerting.yaml${NC}"
fi

if [ -f "config/grafana_dashboard.json" ]; then
    echo -e "${GREEN}✓ config/grafana_dashboard.json${NC}"
else
    echo -e "${RED}✗ config/grafana_dashboard.json${NC}"
fi

if [ -f "config/prometheus.yml" ]; then
    echo -e "${GREEN}✓ config/prometheus.yml${NC}"
else
    echo -e "${YELLOW}⚠ config/prometheus.yml not found${NC}"
    echo "  Create one with:"
    echo "  cat > config/prometheus.yml << 'EOF'"
    echo "global:"
    echo "  scrape_interval: 15s"
    echo "scrape_configs:"
    echo "  - job_name: 'dfp-pipeline'"
    echo "    static_configs:"
    echo "      - targets: ['localhost:8000']"
    echo "EOF"
fi

echo ""
echo "=================================="
echo "Environment Variables:"
echo "=================================="

if [ -n "$SLACK_WEBHOOK_URL" ]; then
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL: SET${NC}"
else
    echo -e "${YELLOW}⚠ SLACK_WEBHOOK_URL: NOT SET${NC}"
fi

if [ -n "$SMTP_USER" ]; then
    echo -e "${GREEN}✓ SMTP_USER: SET${NC}"
else
    echo -e "${YELLOW}⚠ SMTP_USER: NOT SET${NC}"
fi

if [ -n "$SMTP_PASSWORD" ]; then
    echo -e "${GREEN}✓ SMTP_PASSWORD: SET${NC}"
else
    echo -e "${YELLOW}⚠ SMTP_PASSWORD: NOT SET${NC}"
fi

echo ""
echo "=================================="
echo "Recent Metrics:"
echo "=================================="

if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "Latest metrics from http://localhost:8000/metrics:"
    echo ""
    curl -s http://localhost:8000/metrics | grep "^dfp_" | head -20
    echo "..."
    echo ""
    echo "To view all metrics:"
    echo "  curl http://localhost:8000/metrics | grep dfp_"
else
    echo "Metrics server not running. Start a pipeline to collect metrics."
fi

echo ""
echo "=================================="
echo "Recent Alerts:"
echo "=================================="

if [ -f "data/logs/alerts.log" ]; then
    echo "Last 10 alerts:"
    tail -10 data/logs/alerts.log
else
    echo "No alerts logged yet."
fi

echo ""
