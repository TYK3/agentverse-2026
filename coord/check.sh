#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -r coord/requirements.txt
python -m ruff check coord
GEMINI_MODE=off python -m pytest coord/tests -q
