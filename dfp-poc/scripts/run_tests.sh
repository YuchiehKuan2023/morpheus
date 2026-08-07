#!/usr/bin/env bash
###############################################################################
# Test Runner Script
#
# This script runs the complete test suite for the DFP PoC project.
# It ensures tests are run from the correct directory (dfp-poc/) to resolve
# relative path dependencies.
#
# Usage:
#   ./scripts/run_tests.sh                  # Run all tests
#   ./scripts/run_tests.sh -v               # Run with verbose output
#   ./scripts/run_tests.sh -k test_name     # Run specific test
#
# Author: Tomasz Zabek <tzabek@deloitte.co.uk>
# Date: 2025-11-11
###############################################################################

set -e  # Exit on error

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root (dfp-poc/)
cd "$PROJECT_ROOT"

echo "======================================================================"
echo "Running DFP PoC Test Suite"
echo "======================================================================"
echo "Project Root: $PROJECT_ROOT"
echo "Python: $(which python || echo 'Using system python')"
echo "======================================================================"
echo ""

# Activate virtual environment if it exists
if [ -d "../.venv" ]; then
    source ../.venv/bin/activate
    echo "✓ Virtual environment activated"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
fi

# Run pytest with all arguments passed to this script
python -m pytest tests/ "$@"

# Capture exit code
EXIT_CODE=$?

echo ""
echo "======================================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ All tests passed successfully!"
else
    echo "✗ Some tests failed (exit code: $EXIT_CODE)"
fi
echo "======================================================================"

exit $EXIT_CODE
