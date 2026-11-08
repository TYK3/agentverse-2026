#!/usr/bin/env bash
# Run from any directory: bash /path/to/repo/tools/run_local.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v node >/dev/null || { echo "Install Node.js 20.19+ or 22.12+." >&2; exit 1; }
command -v npm >/dev/null || { echo "Install npm." >&2; exit 1; }
if [[ ! -d .venv ]]; then
    "${PYTHON:-python3}" -m venv .venv
fi
python=.venv/bin/python
[[ -x "$python" ]] || python=.venv/Scripts/python.exe
"$python" -m pip install -r requirements.txt -r coord/requirements.txt python-dotenv
if [[ ! -d console/node_modules ]]; then
    (cd console && npm ci)
fi
exec "$python" - <<'PYTHON'
import os
import signal
import subprocess
import sys
import time
from dotenv import load_dotenv

load_dotenv(".env", override=False)
os.environ.setdefault("GEMINI_MODE", "off")
# Headless Linux needs EGL; desktop laptops keep MuJoCo's native default.
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ.setdefault("MUJOCO_GL", "egl")

children = []
def stop(signum, frame):
    raise KeyboardInterrupt

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
try:
    # Fail rather than silently choosing another port or using an unrelated hub.
    import socket
    for port in (8000, 5173):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    commands = [
        [sys.executable, "-m", "uvicorn", "coord.hub:app", "--host", "127.0.0.1", "--port", "8000"],
        ["node", "console/node_modules/vite/bin/vite.js", "console", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
    ]
    for command in commands:
        children.append(subprocess.Popen(
            command, start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        ))
    print("Hub: http://localhost:8000/docs\nConsole: http://localhost:5173/\nPress Ctrl+C to stop both.", flush=True)
    while all(child.poll() is None for child in children):
        time.sleep(0.2)
    raise SystemExit(next((child.returncode or 1 for child in children if child.poll() is not None), 1))
except KeyboardInterrupt:
    pass
finally:
    # Ignore further interrupts whilst both process trees are being stopped.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    for child in children:
        if os.name == "nt":
            if child.poll() is None:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
            child.wait()
PYTHON
