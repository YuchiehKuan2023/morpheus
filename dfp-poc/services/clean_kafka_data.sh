#!/bin/bash

################################################################################
# Clean Kafka Data Script
#
# Removes Kafka logs and resets storage (keeps configuration)
# Use this to reclaim disk space during development
#
# WARNING: This deletes all Kafka messages and consumer offsets!
################################################################################

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo "================================================================================"
echo -e "${YELLOW}Kafka Data Cleanup${NC}"
echo "================================================================================"
echo ""

# Check if Kafka is running
if lsof -Pi :29092 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}ERROR:${NC} Kafka is currently running on port 29092"
    echo -e "Please stop services first: ${BLUE}./services/stop_services.sh${NC}"
    exit 1
fi

# Show current size
if [ -d "data/kafka-logs" ]; then
    CURRENT_SIZE=$(du -sh data/kafka-logs/ | cut -f1)
    echo -e "Current Kafka data size: ${YELLOW}$CURRENT_SIZE${NC}"
    echo ""
else
    echo "No Kafka data found."
    exit 0
fi

# Confirm deletion
echo -e "${YELLOW}WARNING:${NC} This will delete:"
echo -e "  • All Kafka messages (dfp-events, dfp-detections, etc.)"
echo -e "  • All consumer offsets"
echo -e "  • Cluster metadata (will need reformatting)"
echo ""
echo -e "${YELLOW}Configuration will be preserved:${NC}"
echo -e "  • server.properties (kept)"
echo -e "  • cluster.id (will be regenerated on next start)"
echo ""
read -p "Continue? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Cleanup cancelled."
    exit 0
fi

# Remove Kafka logs
echo -e "${BLUE}[INFO]${NC} Removing Kafka logs..."
rm -rf data/kafka-logs/*
echo -e "${GREEN}[SUCCESS]${NC} Kafka logs deleted"

# Remove cluster ID (will be regenerated)
if [ -f "data/kafka/cluster.id" ]; then
    rm -f data/kafka/cluster.id
    echo -e "${GREEN}[SUCCESS]${NC} Cluster ID removed (will regenerate)"
fi

# Show new size
NEW_SIZE=$(du -sh data/kafka-logs/ 2>/dev/null | cut -f1 || echo "0B")
echo -e "New size: ${GREEN}$NEW_SIZE${NC}"

echo ""
echo "================================================================================"
echo -e "${GREEN}Cleanup Complete${NC}"
echo "================================================================================"
echo ""
echo -e "Disk space reclaimed: ${GREEN}$CURRENT_SIZE${NC}"
echo ""
echo "Next steps:"
echo -e "  1. Start services: ${BLUE}./services/start_services.sh${NC}"
echo -e "  2. Kafka will automatically reformat storage with new cluster ID"
echo -e "  3. All topics will be recreated automatically"
echo ""
echo "================================================================================"
