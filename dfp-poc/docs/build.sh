#!/bin/bash
# Build Sphinx documentation

set -e

echo "Building Sphinx documentation..."

# Navigate to docs directory
cd "$(dirname "$0")"

# Install documentation dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Install the package in editable mode (required for autodoc)
echo "Installing dfp-poc package..."
cd .. && pip install -q -e . && cd docs

# Clean previous build
echo "Cleaning previous build..."
rm -rf _build api/_autosummary

# Build HTML documentation (without -W to allow warnings)
echo "Building HTML documentation..."
sphinx-build -b html --keep-going . _build/html

echo "✓ Documentation built successfully!"
echo "  Open: _build/html/index.html"
echo ""
echo "To serve locally:"
echo "  cd _build/html && python -m http.server 8888"
