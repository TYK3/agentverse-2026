#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export GEMINI_MODE=off
uvx ruff check planner
uv run --no-project --with pytest --with pydantic --with fastapi --with psutil python -m pytest planner -q
uv run --no-project python -m planner.fake_run
uv run --no-project --with pydantic python -m planner.loop_run > /dev/null
uv run --no-project python -m planner.report_run > /dev/null
