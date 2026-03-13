#!/usr/bin/env bash
set -euo pipefail

echo "Running Ruff formatter..."
ruff format src/ tests/

echo "Running Ruff lint checks..."
ruff check src/ tests/

echo "Running mypy type checks..."
mypy src/solux/

echo "All pre-commit checks passed."
