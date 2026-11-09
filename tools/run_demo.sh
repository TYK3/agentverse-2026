#!/usr/bin/env bash
# Start the whole AFTERSHOCK demo (T23, issue #31): the hub on :8000 and the console on :5173.
#   bash tools/run_demo.sh            # Ctrl+C stops both
#   HUB_PORT=8001 bash tools/run_demo.sh
# The hub starts every merged lane with start(bus). The console part is skipped until
# console/package.json exists on this branch.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .venv/Scripts/activate ]; then source .venv/Scripts/activate
elif [ -f .venv/bin/activate ]; then source .venv/bin/activate
fi
export GEMINI_MODE="${GEMINI_MODE:-off}"
HUB_PORT="${HUB_PORT:-8000}"
CONSOLE_PORT="${CONSOLE_PORT:-5173}"
mkdir -p runs

pids=()
stop() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap stop EXIT INT TERM

python -c "import coord.hub" 2>/dev/null || { echo "coord/hub.py is missing (PR #47); cannot start the hub"; exit 1; }
echo "hub      http://localhost:$HUB_PORT  (GEMINI_MODE=$GEMINI_MODE, log runs/hub.log)"
uvicorn coord.hub:app --port "$HUB_PORT" >runs/hub.log 2>&1 &
pids+=($!)

if [ -f console/package.json ]; then
  [ -d console/node_modules ] || (cd console && npm install --no-audit --no-fund)
  echo "console  http://localhost:$CONSOLE_PORT"
  (cd console && npm run dev -- --port "$CONSOLE_PORT") &
  pids+=($!)
else
  echo "console  skipped: console/package.json not on this branch yet (PR #43)"
fi

for _ in $(seq 1 50); do
  curl -fs "http://localhost:$HUB_PORT/docs" >/dev/null 2>&1 && { echo "hub up"; break; }
  sleep 0.2
done
wait
