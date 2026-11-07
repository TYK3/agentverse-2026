#!/usr/bin/env bash
# sim lane check, run by CI (.github/workflows/ci.yml) and locally: bash sim/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
uvx ruff check sim
uv run --no-project --with mujoco --with numpy --with pytest python -m pytest sim/tests -q
