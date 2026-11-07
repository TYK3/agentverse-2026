#!/usr/bin/env bash
# perception lane check, run by CI (.github/workflows/ci.yml) and locally: bash perception/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
uvx ruff check perception
uv run --no-project --with pytest python -m pytest perception/tests -q
