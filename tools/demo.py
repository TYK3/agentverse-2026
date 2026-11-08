"""One command for the whole rescue, shown in the console's story mode (ref DEMO-FLOW-2).

    python tools/demo.py                                    # building scene, 120 s, opens the browser
    python tools/demo.py --scene backup --duration 90 --auto-approve --shift-at 45
    python tools/demo.py --replay runs/demo60-7.jsonl       # only open a recording in story mode

What it does, in order:
1. starts the hub (`uvicorn coord.hub:app` on port 8000, where the console connects) with every lane,
   SIM_SCENE=<scene>, and SIM_RECORD writing the run to console/public/runs/demo-<time>.jsonl;
2. starts the console (`npm run dev` on 127.0.0.1:5173) and opens it: story mode, LIVE;
3. while it runs: with --auto-approve it answers each gate/request yes over the browser socket
   (otherwise the operator answers in the console or by voice); with --shift-at S it injects the
   aftershock at S seconds (POST /inject), the unscripted change;
4. after --duration seconds it stops the hub, prints what the recording holds, and opens the same run
   as a story replay (?run=/runs/<file>&speed=<n>); the console keeps serving until Ctrl+C.
--replay <file> skips 1-3: it copies the recording into console/public/runs and opens the replay.
Real lanes only; this script never fakes a message. GEMINI_MODE defaults to off.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "console"
RUNS = CONSOLE / "public" / "runs"          # served by vite at /runs/
HUB_PORT = 8000                              # console/src/bus.ts connects to ws://localhost:8000/ws
CONSOLE_PORT = 5173
HUB = f"http://127.0.0.1:{HUB_PORT}"
CONSOLE_URL = f"http://127.0.0.1:{CONSOLE_PORT}"


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--scene", default="building", help="SIM_SCENE: building (default), tower, backup or an MJCF path")
    p.add_argument("--duration", type=float, default=120.0, help="seconds of live run before the replay")
    p.add_argument("--shift-at", type=float, default=None, help="inject the aftershock at this many seconds")
    p.add_argument("--auto-approve", action="store_true", help="answer every gate/request yes (unattended demo)")
    p.add_argument("--speed", type=float, default=4.0, help="replay speed for the story at the end")
    p.add_argument("--replay", help="open this recording in story mode instead of a live run")
    p.add_argument("--no-browser", action="store_true", help="print the URLs, do not open a browser")
    p.add_argument("--no-console", action="store_true", help="do not start the console dev server")
    a = p.parse_args(argv)
    if a.duration <= 0 or a.speed <= 0:
        p.error("--duration and --speed must be positive")
    if a.shift_at is not None and not 0 <= a.shift_at < a.duration:
        p.error("--shift-at must fall inside --duration")
    return a


def run_name(stamp=None):
    return f"demo-{stamp or time.strftime('%Y%m%d-%H%M%S')}.jsonl"


def hub_command(scene, record, env=None):
    """(argv, env) for the hub with every lane, recording to `record`."""
    env = dict(os.environ if env is None else env)
    env.update({"SIM_SCENE": scene, "SIM_RECORD": str(record)})
    env.setdefault("GEMINI_MODE", "off")
    argv = [sys.executable, "-m", "uvicorn", "coord.hub:app", "--host", "127.0.0.1", "--port", str(HUB_PORT)]
    return argv, env


def console_command():
    npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
    return [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(CONSOLE_PORT), "--strictPort"]


def live_url():
    return f"{CONSOLE_URL}/"


def replay_url(name, speed):
    return f"{CONSOLE_URL}/?run=/runs/{name}&speed={speed:g}"


def answer_for(message):
    """The gate/answer --auto-approve sends for one hub message, or None."""
    if message.get("topic") != "gate/request" or not isinstance(message.get("data"), dict):
        return None
    gate = message["data"].get("id")
    return {"topic": "gate/answer", "data": {"id": gate, "approved": True, "by": "operator"}} if gate else None


def stage_replay(path):
    """Copy a recording into console/public/runs (served at /runs/); returns its name there."""
    src = pathlib.Path(path).resolve()
    RUNS.mkdir(parents=True, exist_ok=True)
    dst = RUNS / src.name
    if src != dst.resolve():
        shutil.copyfile(src, dst)
    return dst.name


def summarize(path):
    """Topic counts and sim-time span of a recording (same as python -m sim.recorder summary)."""
    counts, first, last = {}, None, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            counts[rec.get("topic")] = counts.get(rec.get("topic"), 0) + 1
            first = rec.get("t") if first is None else first
            last = rec.get("t", last)
    return {"topics": counts, "t0": first, "t1": last}


# ---- processes --------------------------------------------------------------------------------
def start(argv, cwd, env=None, log=None):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(argv, cwd=cwd, env=env, stdout=log or subprocess.DEVNULL, stderr=subprocess.STDOUT,
                            creationflags=flags, start_new_session=os.name != "nt")


def stop(proc):
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_http(url, timeout=120.0, opener=urllib.request.urlopen):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener(url, timeout=2):
                return True
        except OSError:
            time.sleep(1.0)
    return False


def inject_aftershock(opener=urllib.request.urlopen):
    req = urllib.request.Request(f"{HUB}/inject", data=json.dumps({"kind": "aftershock"}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with opener(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


async def drive(duration, shift_at, auto_approve):
    """The live part: auto-approve over the browser socket, the aftershock at shift_at, for duration s."""
    started = time.monotonic()
    tasks = []
    if auto_approve:
        import websockets  # only needed for --auto-approve

        async def approver():
            async with websockets.connect(f"ws://127.0.0.1:{HUB_PORT}/ws", max_size=None) as ws:
                async for raw in ws:
                    reply = answer_for(json.loads(raw))
                    if reply:
                        await ws.send(json.dumps(reply))
                        print(f"  auto-approved {reply['data']['id']}", flush=True)
        tasks.append(asyncio.create_task(approver()))
    if shift_at is not None:
        await asyncio.sleep(shift_at)
        print(f"  t+{time.monotonic() - started:.0f}s aftershock: {inject_aftershock()}", flush=True)
    await asyncio.sleep(max(0.0, duration - (time.monotonic() - started)))
    for t in tasks:
        t.cancel()


def open_url(url, no_browser):
    print(f"  {url}", flush=True)
    if not no_browser:
        webbrowser.open(url)


def main(argv=None):
    a = parse(argv)
    hub = console = None
    try:
        if not a.no_console:
            console = start(console_command(), CONSOLE)
            if not wait_http(CONSOLE_URL):
                raise SystemExit("console dev server did not start (cd console && npm install)")
        if a.replay:
            name = stage_replay(a.replay)
            print(f"story replay of {a.replay}:")
            open_url(replay_url(name, a.speed), a.no_browser)
        else:
            RUNS.mkdir(parents=True, exist_ok=True)
            name = run_name()
            record = RUNS / name
            argv, env = hub_command(a.scene, record)
            log = open(RUNS / (name + ".hub.log"), "w", encoding="utf-8")  # noqa: SIM115 (closed with the hub)
            hub = start(argv, ROOT, env, log)
            if not wait_http(f"{HUB}/docs"):
                raise SystemExit(f"hub did not start; see {log.name}")
            print(f"live run, scene {a.scene}, {a.duration:g} s, recording {record.relative_to(ROOT)}:")
            open_url(live_url(), a.no_browser or a.no_console)
            asyncio.run(drive(a.duration, a.shift_at, a.auto_approve))
            stop(hub)
            log.close()
            hub = None
            s = summarize(record)
            print(f"recorded {sum(s['topics'].values())} messages, sim t {s['t0']} .. {s['t1']} s")
            print("  " + ", ".join(f"{k} {v}" for k, v in sorted(s["topics"].items())))
            print("story replay:")
            open_url(replay_url(name, a.speed), a.no_browser or a.no_console)
        if console is not None:
            print("console running; Ctrl+C to stop", flush=True)
            while console.poll() is None:
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        stop(hub)
        stop(console)


if __name__ == "__main__":
    main()
