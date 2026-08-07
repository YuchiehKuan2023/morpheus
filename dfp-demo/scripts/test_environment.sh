#!/bin/bash
# Test Phase 0 environment setup
# This script verifies all Phase 0 requirements

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Use python3 explicitly
PYTHON_CMD="python3"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Phase 0 Environment Testing${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Change to dfp-demo directory to fix module imports
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="${PWD}:${PYTHONPATH}"

echo -e "${YELLOW}Working directory:${NC} ${PWD}"
echo -e "${YELLOW}PYTHONPATH:${NC} ${PYTHONPATH}"
echo -e "${YELLOW}Python command:${NC} ${PYTHON_CMD}"
echo ""

# Test 1: PyTorch installation
echo -e "${YELLOW}[Test 1]${NC} Testing PyTorch installation..."
${PYTHON_CMD} -c "import torch; print(f'✓ PyTorch version: {torch.__version__}')" || {
    echo -e "${RED}✗ Failed to import PyTorch${NC}"
    exit 1
}

# Test 2: PyTorch device detection
echo -e "${YELLOW}[Test 2]${NC} Testing PyTorch device detection..."
${PYTHON_CMD} -c "import torch; print(f'✓ CUDA available: {torch.cuda.is_available()}'); print(f'✓ MPS available: {torch.backends.mps.is_available() if hasattr(torch.backends, \"mps\") else False}')" || {
    echo -e "${RED}✗ Failed device detection${NC}"
    exit 1
}

# Test 3: Core dependencies
echo -e "${YELLOW}[Test 3]${NC} Testing core dependencies..."
${PYTHON_CMD} -c "import pandas; import sklearn; import mlflow; print('✓ pandas, sklearn, mlflow imported successfully')" || {
    echo -e "${RED}✗ Failed to import core dependencies${NC}"
    exit 1
}

# Test 4: Custom modules - environment_utils
echo -e "${YELLOW}[Test 4]${NC} Testing modules.utils.environment_utils..."
${PYTHON_CMD} -c "from modules.utils import get_device, print_system_info; device = get_device(); print(f'✓ Detected device: {device}')" || {
    echo -e "${RED}✗ Failed to import environment_utils${NC}"
    exit 1
}

# Test 5: Custom modules - config_utils
echo -e "${YELLOW}[Test 5]${NC} Testing modules.utils.config_utils..."
${PYTHON_CMD} -c "from modules.utils import load_config; print('✓ config_utils imported successfully')" || {
    echo -e "${RED}✗ Failed to import config_utils${NC}"
    exit 1
}

# Test 6: Custom modules - logging_utils
echo -e "${YELLOW}[Test 6]${NC} Testing modules.utils.logging_utils..."
${PYTHON_CMD} -c "from modules.utils import setup_logging, get_logger; print('✓ logging_utils imported successfully')" || {
    echo -e "${RED}✗ Failed to import logging_utils${NC}"
    exit 1
}

# Test 7: Custom modules - mlflow_utils
echo -e "${YELLOW}[Test 7]${NC} Testing modules.utils.mlflow_utils..."
${PYTHON_CMD} -c "from modules.utils import MLflowManager; print('✓ mlflow_utils imported successfully')" || {
    echo -e "${RED}✗ Failed to import mlflow_utils${NC}"
    exit 1
}

# Test 8: Print system information
echo ""
echo -e "${YELLOW}[Test 8]${NC} System Information:"
${PYTHON_CMD} -c "from modules.utils import print_system_info; print_system_info()"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ All Phase 0 tests passed!${NC}"
echo -e "${GREEN}========================================${NC}"
