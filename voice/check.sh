#!/usr/bin/env bash
# voice lane check, run by CI (.github/workflows/ci.yml) and locally: bash voice/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
uvx ruff check voice
GEMINI_MODE=off uv run --no-project --with pytest --with pydantic --with numpy python -m pytest voice/tests -q
