# Contributing to Morpheus DFP

Thank you for your interest in contributing to the Morpheus Digital Fingerprinting Platform! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Coding Standards](#coding-standards)
- [Documentation](#documentation)
- [Community](#community)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Git
- Docker (optional, for containerized development)

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:

   ```bash
   git clone https://github.com/YOUR-USERNAME/morpheus-dfp.git
   cd morpheus-dfp/dfp-demo
   ```

3. Add the upstream repository:

   ```bash
   git remote add upstream https://github.com/Deloitte-UK-Innersource/morpheus-dfp.git
   ```

## Development Setup

### 1. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
# Install project dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -e ".[dev]"
```

### 3. Install Pre-commit Hooks

```bash
pre-commit install
```

This will run code formatting and linting automatically before each commit.

### 4. Verify Setup

```bash
# Run tests
pytest tests/

# Check code formatting
black --check modules/ pipelines/ scripts/
ruff check modules/ pipelines/ scripts/
mypy modules/ pipelines/ scripts/
```

## Making Changes

### 1. Create a Branch

Always create a new branch for your changes:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

Use descriptive branch names:

- `feature/fft-implementation` - New features
- `fix/velocity-calculation-bug` - Bug fixes
- `docs/api-documentation` - Documentation
- `refactor/preprocessing-module` - Code refactoring
- `test/integration-tests` - Test improvements

### 2. Make Your Changes

- Write clear, concise commit messages using [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat: add FFT time-series burst detection`
  - `fix: correct haversine distance calculation`
  - `docs: update README with installation instructions`
  - `test: add unit tests for preprocessing module`
  - `refactor: simplify AnomalyFilter logic`
  - `perf: optimize AutoEncoder inference speed`
  - `chore: update dependencies`

- Keep commits focused and atomic
- Write meaningful commit messages

### 3. Follow Coding Standards

See [Coding Standards](#coding-standards) section below.

## Testing

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_preprocessing.py

# Run with coverage
pytest --cov=modules --cov=pipelines --cov-report=html

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

### Writing Tests

- Place tests in `tests/` directory
- Follow naming convention: `test_*.py`
- Use descriptive test function names: `test_velocity_calculation_with_missing_coordinates()`
- Use pytest fixtures for reusable test setup
- Mark tests appropriately:

  ```python
  import pytest

  @pytest.mark.unit
  def test_basic_functionality():
      pass

  @pytest.mark.integration
  def test_pipeline_integration():
      pass

  @pytest.mark.slow
  def test_expensive_operation():
      pass
  ```

### Test Coverage

- Aim for >80% test coverage for new code
- Focus on testing edge cases and error conditions
- Include integration tests for pipeline components

## Submitting Changes

### 1. Update Your Branch

Before submitting, ensure your branch is up to date:

```bash
git fetch upstream
git rebase upstream/main
```

### 2. Run Final Checks

```bash
# Format code
black modules/ pipelines/ scripts/ tests/

# Lint
ruff check modules/ pipelines/ scripts/ tests/ --fix

# Type check
mypy modules/ pipelines/ scripts/

# Run tests
pytest tests/
```

### 3. Push Changes

```bash
git push origin feature/your-feature-name
```

### 4. Create Pull Request

1. Go to GitHub and create a Pull Request
2. Fill out the PR template completely
3. Link any related issues
4. Request review from maintainers

### Pull Request Guidelines

- **Title**: Use conventional commit format: `feat: add FFT implementation`
- **Description**: Clearly describe what changes were made and why
- **Tests**: Include test results
- **Documentation**: Update docs if needed
- **Breaking Changes**: Clearly mark and explain any breaking changes

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/)
- Use [Black](https://black.readthedocs.io/) for code formatting (120 char line length)
- Use [Ruff](https://docs.astral.sh/ruff/) for linting
- Use [mypy](http://mypy-lang.org/) for type checking

### Code Organization

```python
"""Module docstring explaining purpose."""

import standard_library
import third_party
import local_modules

# Constants
MAX_RETRIES = 3
DEFAULT_THRESHOLD = 2.0

# Classes and functions
class MyClass:
    """Class docstring."""

    def __init__(self, param: str) -> None:
        """Initialize with clear parameter descriptions."""
        self.param = param

    def method(self, arg: int) -> bool:
        """
        Method description.

        Args:
            arg: Description of argument

        Returns:
            Description of return value

        Raises:
            ValueError: When arg is negative
        """
        if arg < 0:
            raise ValueError("arg must be non-negative")
        return True
```

### Configuration

- Use type-safe configuration (Pydantic models)
- Provide sensible defaults
- Validate configuration at startup
- Document all configuration options

## Documentation

- Use Google-style docstrings
- Document all public functions, classes, and modules
- Include type hints for function signatures
- Add inline comments for complex logic

### Code Documentation

- Keep docstrings up to date
- Document parameters, return values, and exceptions
- Include usage examples for complex functions

### Project Documentation

- Update `README.md` for user-facing changes
- Update `docs/` for technical documentation
- Add configuration examples when adding new features
- Update changelog (automated via conventional commits)

### API Documentation

- Document all public APIs
- Include code examples
- Document configuration options
- Explain behavior and edge cases

## Community

### Getting Help

- **Issues**: Use GitHub Issues for bug reports and feature requests
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Documentation**: Check the `docs/` directory

### Communication

- Be respectful and constructive
- Provide context and examples when asking questions
- Help others when you can

### Review Process

- Maintainers will review PRs within 3-5 business days
- Address review feedback promptly
- Be open to suggestions and improvements
- CI/CD checks must pass before merge

## Release Process

Releases are automated:

1. Merge PRs to `main` using conventional commits
2. Version is automatically determined from commit messages
3. Tag created: `v1.2.3`
4. Release workflow builds and publishes artifacts
5. Changelog generated automatically

## Recognition

Contributors will be recognized in:

- `CONTRIBUTORS.md` file
- Release notes
- Project documentation

---

Thank you for contributing to Morpheus DFP! 🚀
