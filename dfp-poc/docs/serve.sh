#!/bin/bash
set -e
# Serve documentation locally

cd "$(dirname "$0")"

if [ ! -d "_build/html" ]; then
    echo "Documentation not built. Building now..."
    ./build.sh
fi

echo "Starting local documentation server..."
echo "Documentation available at: http://localhost:8888"
echo "Press Ctrl+C to stop"

cd _build/html && python -m http.server 8888
