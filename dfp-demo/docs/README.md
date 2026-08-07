# Morpheus DFP Documentation

This directory contains the Sphinx documentation for the Morpheus Digital Fingerprinting Platform.

## Building Documentation

### Prerequisites

Install documentation dependencies:

```bash
pip install -r requirements.txt
```

### Build HTML

```bash
./build.sh
```

This generates HTML documentation in `_build/html/`.

### Serve Locally

```bash
./serve.sh
```

Access documentation at <http://localhost:8888>

Note: Port 8888 is used to avoid conflicts with Kafka UI (8080) and inference metrics (8000).

## Documentation Structure

```text
docs/
├── conf.py                 # Sphinx configuration
├── index.rst               # Documentation home
├── getting_started.rst     # Installation and quickstart
├── architecture.rst        # System architecture
├── examples.rst            # Usage examples
├── configuration.rst       # Configuration reference
├── deployment.rst          # Production deployment
├── api/                    # API reference
│   ├── index.rst          # API overview
│   ├── preprocessing.rst  # Preprocessing module
│   ├── training.rst       # Training module
│   ├── inference.rst      # Inference module
│   ├── io.rst             # I/O module
│   ├── control.rst        # Control module
│   └── utils.rst          # Utilities module
├── build.sh               # Build script
├── serve.sh               # Local server script
└── requirements.txt       # Documentation dependencies
```

## Writing Documentation

### Adding New Pages

1. Create `.rst` file in `docs/`
2. Add to `index.rst` toctree
3. Rebuild documentation

### Documenting Code

Use Google-style docstrings:

```python
def example_function(param1: str, param2: int) -> bool:
    """
    Brief description of function.
    
    Longer description if needed.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When param2 is negative
        
    Example:
        >>> result = example_function("test", 42)
        >>> print(result)
        True
    """
    if param2 < 0:
        raise ValueError("param2 must be non-negative")
    return True
```

### Adding Examples

Add code examples in `.rst` files:

```rst
Example Usage
~~~~~~~~~~~~~

.. code-block:: python

   from modules.training.dfp_trainer import DFPTrainer
   
   trainer = DFPTrainer(config)
   result = trainer.train(message)
```

## Deployment

### GitHub Pages

The documentation can be deployed to GitHub Pages:

1. Build documentation: `./build.sh`
2. Copy `_build/html/` to `gh-pages` branch
3. Push to GitHub

### Read the Docs

Configure `.readthedocs.yaml`:

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.11"

sphinx:
  configuration: docs/conf.py

python:
  install:
    - requirements: docs/requirements.txt
    - method: pip
      path: .
```

## Troubleshooting

### Missing Modules

If autodoc fails to import modules:

```bash
# Ensure package is installed
pip install -e .

# Check sys.path in conf.py
python -c "import sys; print(sys.path)"
```

### Build Warnings

Fix warnings before deployment:

```bash
# Build with warnings as errors
sphinx-build -W -b html . _build/html
```

### Theme Issues

Reinstall theme if styling is broken:

```bash
pip install --upgrade --force-reinstall sphinx-rtd-theme
```

## Resources

- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [reStructuredText Primer](https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html)
- [Google Style Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [Read the Docs](https://docs.readthedocs.io/)
