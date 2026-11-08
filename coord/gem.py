"""The one Gemini door (T26). Every Gemini call made by product code goes through here.

    from coord import gem
    try:
        text = gem.ask("fast_subagent", prompt, feature="vision")
    except gem.GeminiOff:
        gem.mark_stand_in("vision")      # then use your own labelled local stand-in
        text = local_stand_in(prompt)

GEMINI_MODE (environment):
    off     default while building. ask() raises GeminiOff and never imports google.genai.
    replay  return the cached answer for the same request; on a miss, call once and cache it.
    live    real calls (the demo). Answers are still written to the cache.
GEMINI_CAP_PER_HOUR caps real calls across the process (default 300).
The key comes from GEMINI_API_KEY (environment or .env), never from code.

Live and Gemma sessions (T21, T22, T15) use their own client, but call count_call() once per
session or request so they count toward the cap, and mark_stand_in() when they fall back.
"""
import hashlib
import json
import os
import pathlib
import threading
import time

MODEL_IDS = {  # copied from the Builder Guide; change model IDs here only
    "lead_reasoning": "gemini-4-argon",
    "managed_sandbox": "antigravity-preview-09-2026",
    "fast_subagent": "gemini-3.8-flash",
    "fast_router": "gemini-3.5-flash-lite",
    "live_voice_vision": "gemini-3.8-live",
    "live_translate": "gemini-3.5-live-translate-preview",
    "tts_studio": "gemini-3.8-flash-tts",
    "open_model": "gemma-4-31b-it",
}
MODE = os.environ.get("GEMINI_MODE", "off")  # off | replay | live
CAP = int(os.environ.get("GEMINI_CAP_PER_HOUR", "300"))  # stay far below "thousands of requests"
CACHE = pathlib.Path(__file__).resolve().parent.parent / ".gem_cache"  # repo root, gitignored
RETRY_ON = ("429", "503")

_calls: list[float] = []
_lock = threading.Lock()
_client = None
stand_ins: set[str] = set()  # features that ran without Gemini, for the console badge


class GeminiOff(Exception):
    """Raised by ask() in off mode. The caller uses its own stand-in and calls mark_stand_in()."""


def _c():
    global _client
    if _client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        from google import genai
        _client = genai.Client()  # reads GEMINI_API_KEY
    return _client


def count_call(feature="?"):
    """Count one real call against the hourly cap. Raises RuntimeError when the cap is reached."""
    with _lock:
        now = time.time()
        _calls[:] = [t for t in _calls if now - t < 3600]
        if len(_calls) >= CAP:
            raise RuntimeError(f"gemini call cap reached ({CAP}/h, feature {feature}); "
                               "raise GEMINI_CAP_PER_HOUR on purpose")
        _calls.append(now)


def _cache_file(model_key, input, thinking, config):
    raw = json.dumps([model_key, thinking, str(input), config], sort_keys=True, default=str)
    return CACHE / f"{hashlib.sha256(raw.encode()).hexdigest()}.txt"


def ask(model_key, input, thinking="medium", feature="?", **config):
    """Return the model's text. Raises GeminiOff in off mode, KeyError for an unknown model_key."""
    if MODE == "off":
        raise GeminiOff(feature)
    model = MODEL_IDS[model_key]
    f = _cache_file(model_key, input, thinking, config)
    if MODE == "replay" and f.exists():
        return f.read_text(encoding="utf-8")
    count_call(feature)
    for attempt in range(3):  # retry 429 and 503 only, short backoff
        try:
            r = _c().interactions.create(model=model, input=input,
                                         generation_config={"thinking_level": thinking, **config})
            text = r.output_text or ""
            CACHE.mkdir(exist_ok=True)
            f.write_text(text, encoding="utf-8")
            return text
        except Exception as e:
            if attempt == 2 or not any(code in str(e) for code in RETRY_ON):
                raise
            time.sleep(2 ** attempt)


def mark_stand_in(feature):
    stand_ins.add(feature)


def status():
    """The status/gemini message body, published every 2 s by the hub."""
    with _lock:
        now = time.time()
        calls = sum(1 for t in _calls if now - t < 3600)
    return {"mode": MODE, "calls_last_hour": calls, "stand_ins": sorted(stand_ins)}
