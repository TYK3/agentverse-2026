"""T15: the offline model, Gemma 4 E2B running locally under Ollama. No network beyond localhost.

Used only to read an operator's goal ("send water to the back room" -> place, item, one-line why).
Never for the safety decision: routes, physics, the gate and the human gate stay rule-based.

    ollama serve & ollama pull gemma4:e2b      # tag checked in Ollama's registry, 7 Nov 2026

If the runtime is missing or slow, `interpret` falls back to a labelled keyword parser.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
MODEL_TAG = os.environ.get("PLANNER_LOCAL_MODEL", "gemma4:e2b")
MODEL_NAME = "gemma-4-local"  # what log/decision and route/proposed call it
TIMEOUT_S = float(os.environ.get("PLANNER_LOCAL_TIMEOUT", "20"))
KEEP_ALIVE = "2h"  # stay loaded for the whole demo: a cold load takes ~19 s on the demo laptop
ITEMS = {"water": ("water", "bottle", "drink"), "first_aid_kit": ("first aid", "medkit", "kit", "bandage"),
         "radio": ("radio", "walkie")}


class LocalLLMUnavailable(RuntimeError):
    """The local runtime is not running, does not have the model, or timed out."""


def _url(path):
    host = HOST if HOST.startswith("http") else f"http://{HOST}"
    return host.rstrip("/") + path


def _post(path, body, timeout):
    req = urllib.request.Request(_url(path), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # localhost runtime only
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise LocalLLMUnavailable(f"{MODEL_TAG} at {HOST}: {e}") from e


def ask(prompt: str, *, json_mode=False, timeout=TIMEOUT_S, max_tokens=120) -> str:
    """One completion from the local model. Raises LocalLLMUnavailable."""
    body = {"model": MODEL_TAG, "prompt": prompt, "stream": False, "think": False, "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": max_tokens}}
    if json_mode:
        body["format"] = "json"
    return _post("/api/generate", body, timeout).get("response", "")


def warm(timeout=120.0) -> bool:
    """Load the model before the run (the cold load is the slow part). True when it answered."""
    try:
        ask("Reply with: ok", timeout=timeout, max_tokens=2)
    except LocalLLMUnavailable:
        return False
    return True


RUNNERS = ("llama-server", "ollama runner", "ollama_llama_server")


def _runner_rss_mb() -> float:
    """Resident memory of the runtime's model processes. /api/ps "size" undercounts on CPU
    (it reported 1.0 GB for gemma4:e2b while llama-server held 4.1 GB), so measure the processes."""
    try:
        import psutil
        procs = ((" ".join(p.info["cmdline"] or []), p.info["memory_info"].rss)
                 for p in psutil.process_iter(["cmdline", "memory_info"]))
        return sum(rss for cmd, rss in procs if any(r in cmd for r in RUNNERS)) / 1e6
    except ImportError:
        pass
    total = 0
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if any(r in cmd for r in RUNNERS):
                total += int((proc / "statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    return total / 1e6


def loaded_mb() -> float:
    """Memory the local runtime holds for the loaded model, 0 when nothing is loaded."""
    try:
        req = urllib.request.Request(_url("/api/ps"))
        with urllib.request.urlopen(req, timeout=1) as r:  # localhost runtime only
            models = json.loads(r.read()).get("models", [])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0.0
    if not models:
        return 0.0
    return max(_runner_rss_mb(), sum(m.get("size", 0) for m in models) / 1e6)


def _keywords(text: str, places: list[str]) -> dict:
    low = text.lower()
    # The last mention wins, so "the left room, no, the back room" resolves to the back room.
    place = max(places, key=lambda p: low.rfind(p.lower()), default=None)
    if place is not None and low.rfind(place.lower()) < 0:
        place = None
    item = None
    for name, words in ITEMS.items():
        pos = max(low.rfind(w) for w in words)
        if pos >= 0 and (item is None or pos > item[1]):
            item = (name, pos)
    return {"place": place, "item": item[0] if item else None}


def interpret(text: str, places: list[str], *, use_model=True) -> dict:
    """Operator goal -> {"place", "item", "why", "model"}. `place` is one of `places` or None."""
    if use_model:
        prompt = (
            "A rescue operator gave a command. Pick the destination from this list only: "
            f"{json.dumps(places)}. Items: water, first_aid_kit, radio. If they change their mind, "
            "use the final choice. Reply with JSON only: "
            '{"place": "<from the list or null>", "item": "<item or null>", "why": "<one short line>"}\n'
            f"Command: {text}")
        try:
            raw = ask(prompt, json_mode=True)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            out = json.loads(match.group(0)) if match else {}
            place = out.get("place") if out.get("place") in places else None
            item = out.get("item") if out.get("item") in ITEMS else None
            if place:
                return {"place": place, "item": item, "why": str(out.get("why") or "")[:160],
                        "model": MODEL_NAME}
        except (LocalLLMUnavailable, ValueError, AttributeError):
            pass
    out = _keywords(text, places)
    return {**out, "why": "keyword match (local model unavailable)", "model": "keyword-stand-in"}
