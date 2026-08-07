#!/usr/bin/env bash
#
# DFP Monitoring Service Stop
#
# Stops monitoring services (metrics server, alert manager).
# Note: Prometheus and Grafana are typically managed separately.
#
# Note: This script is automatically called by stop_services.sh
#       You don't need to run it separately unless you want to stop monitoring only.
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=================================="
echo "DFP Monitoring Services - STOP"
echo "=================================="

# Metrics server is managed by the pipeline (stops when pipeline stops)
echo -e "${GREEN}✓ Metrics server is managed by pipeline${NC}"
echo "  Server stops automatically when pipeline exits"

if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠ Metrics server still running on port 8000${NC}"
    echo "  This means a pipeline is still running"
fi

echo ""
echo "=================================="
echo "Stopping Optional Services"
echo "=================================="

# Stop Pushgateway if running
if lsof -Pi :9091 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠ Pushgateway running on port 9091${NC}"
    echo "  Stopping process..."
    lsof -ti :9091 | xargs kill 2>/dev/null && echo -e "${GREEN}✓ Pushgateway stopped${NC}" || echo -e "${RED}✗ Failed${NC}"
else
    echo -e "${GREEN}✓ Pushgateway not running${NC}"
fi

# Stop Prometheus if running
if lsof -Pi :9090 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠ Prometheus running on port 9090${NC}"
    if brew services list 2>/dev/null | grep -q "prometheus.*started"; then
        echo "  Stopping via brew services..."
        brew services stop prometheus 2>/dev/null && echo -e "${GREEN}✓ Prometheus stopped${NC}" || echo -e "${RED}✗ Failed${NC}"
    else
        echo "  Stopping process..."
        lsof -ti :9090 | xargs kill 2>/dev/null && echo -e "${GREEN}✓ Prometheus stopped${NC}" || echo -e "${RED}✗ Failed${NC}"
    fi
else
    echo -e "${GREEN}✓ Prometheus not running${NC}"
fi

# Stop Grafana if running
if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠ Grafana running on port 3000${NC}"
    if brew services list 2>/dev/null | grep -q "grafana.*started"; then
        echo "  Stopping via brew services..."
        brew services stop grafana 2>/dev/null && echo -e "${GREEN}✓ Grafana stopped${NC}" || echo -e "${RED}✗ Failed${NC}"
    else
        echo "  Stopping process..."
        lsof -ti :3000 | xargs kill 2>/dev/null && echo -e "${GREEN}✓ Grafana stopped${NC}" || echo -e "${RED}✗ Failed${NC}"
    fi
else
    echo -e "${GREEN}✓ Grafana not running${NC}"
fi

echo ""
