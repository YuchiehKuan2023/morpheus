#!/bin/bash
# Configure Prometheus to use DFP AI metrics configuration
# Usage: ./services/configure_prometheus.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DFP_CONFIG="$PROJECT_ROOT/config/prometheus.yml"

# Auto-detect Prometheus config path or use environment variable override
if [ -n "$PROMETHEUS_CONFIG" ]; then
    PROMETHEUS_CONFIG_PATH="$PROMETHEUS_CONFIG"
elif [ -f "/opt/homebrew/etc/prometheus.yml" ]; then
    # ARM Mac (Apple Silicon)
    PROMETHEUS_CONFIG_PATH="/opt/homebrew/etc/prometheus.yml"
elif [ -f "/usr/local/etc/prometheus.yml" ]; then
    # Intel Mac
    PROMETHEUS_CONFIG_PATH="/usr/local/etc/prometheus.yml"
elif [ -f "/etc/prometheus/prometheus.yml" ]; then
    # Linux (systemd)
    PROMETHEUS_CONFIG_PATH="/etc/prometheus/prometheus.yml"
else
    echo "Error: Could not find Prometheus config file"
    echo "Checked locations:"
    echo "  - /opt/homebrew/etc/prometheus.yml (ARM Mac)"
    echo "  - /usr/local/etc/prometheus.yml (Intel Mac)"
    echo "  - /etc/prometheus/prometheus.yml (Linux)"
    echo ""
    echo "Set PROMETHEUS_CONFIG environment variable to specify custom path:"
    echo "  export PROMETHEUS_CONFIG=/path/to/prometheus.yml"
    echo "  ./services/configure_prometheus.sh"
    exit 1
fi

echo "=== Configuring Prometheus for AI Metrics ==="
echo "DFP Config: $DFP_CONFIG"
echo "Prometheus Config: $PROMETHEUS_CONFIG_PATH"
echo ""

# Check if config file exists
if [ ! -f "$DFP_CONFIG" ]; then
    echo "Config file not found: $DFP_CONFIG"
    exit 1
fi

# Backup existing Prometheus config
if [ -f "$PROMETHEUS_CONFIG_PATH" ]; then
    BACKUP="$PROMETHEUS_CONFIG_PATH.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Backing up existing config:"
    echo "   $PROMETHEUS_CONFIG_PATH → $BACKUP"
    cp "$PROMETHEUS_CONFIG_PATH" "$BACKUP"
fi

# Copy DFP config to Prometheus location
echo "Copying DFP config to Prometheus:"
echo "   $DFP_CONFIG → $PROMETHEUS_CONFIG_PATH"
cp "$DFP_CONFIG" "$PROMETHEUS_CONFIG_PATH"

# Restart Prometheus (detect service manager)
echo "Restarting Prometheus..."
if command -v brew > /dev/null 2>&1 && brew services list | grep -q prometheus; then
    # Homebrew (macOS)
    brew services restart prometheus
elif command -v systemctl > /dev/null 2>&1; then
    # systemd (Linux)
    sudo systemctl restart prometheus
else
    echo "Warning: Could not detect service manager"
    echo "Please restart Prometheus manually"
fi

# Wait for startup
sleep 3

# Verify
if curl -s http://localhost:9090/-/healthy > /dev/null 2>&1; then
    echo ""
    echo "Prometheus configured and restarted successfully!"
    echo ""
    echo "Scraping Targets:"
    echo "  • dfp-pipeline (localhost:8000)"
    echo "  • pushgateway (localhost:9091)"
    echo "  • prometheus (localhost:9090)"
    echo "  • qdrant (localhost:6333) - AI Module"
    echo "  • mlflow (localhost:5001) - AI Module"
    echo "  • backend-api (localhost:8000) - AI Module"
    echo ""
    echo "View targets: http://localhost:9090/targets"
    echo "View metrics: http://localhost:9090/graph"
else
    echo ""
    echo "Prometheus restarted but health check failed"
    echo "Check Prometheus logs:"
    if [ -f "/opt/homebrew/var/log/prometheus.err.log" ]; then
        echo "   /opt/homebrew/var/log/prometheus.err.log (Homebrew ARM)"
    elif [ -f "/usr/local/var/log/prometheus.err.log" ]; then
        echo "   /usr/local/var/log/prometheus.err.log (Homebrew Intel)"
    else
        echo "   journalctl -u prometheus (systemd)"
        echo "   Or check your Prometheus installation's log location"
    fi
    exit 1
fi
