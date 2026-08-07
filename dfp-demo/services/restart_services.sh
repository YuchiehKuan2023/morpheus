#!/bin/bash

################################################################################
# Restart DFP Services
# 
# This script stops all services and then starts them again.
# Convenience wrapper around stop_services.sh and start_services.sh
#
# Usage:
#   ./restart_services.sh              # Restart all services
#   ./restart_services.sh inference    # Restart only inference pipeline
#   ./restart_services.sh training     # Restart only training pipeline
################################################################################

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT" || exit 1

echo ""
echo "================================================================================"
echo "Restarting DFP Services"
echo "================================================================================"
echo ""

# Stop services first
echo "[INFO] Stopping services..."
bash "${SCRIPT_DIR}/stop_services.sh"

if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to stop services"
    exit 1
fi

# Wait a moment for clean shutdown
echo ""
echo "[INFO] Waiting for clean shutdown..."
sleep 2

# Start services
echo ""
echo "[INFO] Starting services..."
bash "${SCRIPT_DIR}/start_services.sh" "$@"

if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to start services"
    exit 1
fi

echo ""
echo "[SUCCESS] Services restarted successfully"
echo ""
