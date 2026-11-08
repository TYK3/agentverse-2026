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
import uuid
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime

MODEL_IDS = {  # copied from the Builder Guide; change model IDs here only
    "lead_reasoning": "gemini-4-argon",
    "managed_sandbox": "antigravity-preview-09-2026",
    "fast_subagent": "gemini-3.8-flash",
    "fast_router": "gemini-3.5-flash-lite",
    "live_voice_vision": "gemini-3.8-live",
    "live_translate": "gemini-3.5-live-translate-preview",
    "tts_studio": "gemini-3.8-flash-tts",
    "open_model": "gemma-4-31b-it",
    "embodied_reasoning": "gemini-robotics-er-2-preview",
}
MODE = os.environ.get("GEMINI_MODE", "off")  # off | replay | live
CAP = int(os.environ.get("GEMINI_CAP_PER_HOUR", "300"))  # stay far below "thousands of requests"
CACHE = pathlib.Path(__file__).resolve().parent.parent / ".gem_cache"  # repo root, gitignored
RETRY_ON = ("429", "503")

_calls: list[float] = []
_lock = threading.Lock()
_client = None
stand_ins: set[str] = set()  # features that ran without Gemini, for the console badge
_receipts = deque(maxlen=200)  # bounded process history; copies returned to callers


class GeminiOff(Exception):
    """Raised by ask() in off mode. The caller uses its own stand-in and calls mark_stand_in()."""


class GeminiCap(RuntimeError):
    """The live-attempt budget is exhausted; no further SDK call was made."""


@dataclass(frozen=True)
class AskResult:
    text: str
    receipt: dict


def receipts():
    """Copies of the latest 200 completed calls; never includes prompts, media or model text."""
    with _lock:
        return deepcopy(list(_receipts))


def _usage(response):
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    fields = ("total_input_tokens", "total_output_tokens", "total_cached_tokens",
              "total_thought_tokens", "total_tool_use_tokens", "total_tokens")
    return {name: value for name in fields
            if type(value := (usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None))) is int
            and value >= 0} or None


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _cache_origin(path, text):
    """Legacy/corrupt sidecars never manufacture provider attribution for replayed text."""
    try:
        origin = json.loads(path.with_suffix(".receipt.json").read_text(encoding="utf-8"))
        if (isinstance(origin, dict) and origin.get("output_sha256") == hashlib.sha256(text.encode()).hexdigest()
                and origin.get("source") == "live"):
            return origin
    except (OSError, ValueError):
        pass
    return {}


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
            raise GeminiCap(f"gemini call cap reached ({CAP}/h, feature {feature}); "
                               "raise GEMINI_CAP_PER_HOUR on purpose")
        _calls.append(now)


def _cache_file(model_key, input, thinking, config):
    raw = json.dumps([model_key, thinking, str(input), config], sort_keys=True, default=str)
    return CACHE / f"{hashlib.sha256(raw.encode()).hexdigest()}.txt"


def ask(model_key, input, thinking="medium", feature="?", *, route=None, evidence_ids=(), **config):
    """Backwards-compatible text result. Use ask_with_receipt() when linking an action to a call."""
    return ask_with_receipt(model_key, input, thinking, feature, route=route,
                            evidence_ids=evidence_ids, **config).text


def ask_with_receipt(model_key, input, thinking="medium", feature="?", *, route=None, evidence_ids=(), **config):
    """Return AskResult(text, receipt), with truthful source/attempt/usage metadata (G1).

    `route` matches permit/route.route; `evidence_ids` are caller-owned observation IDs.
    They never reach the SDK or the cache key. Failures retain their original exception
    and expose its `.gemini_receipt`; disabled calls never import the SDK.
    """
    began = time.perf_counter()
    receipt = {"id": "gem-" + uuid.uuid4().hex, "schema_version": 1,
               "started_at": datetime.now(UTC).isoformat(), "feature": feature,
               "model_key": model_key, "model_requested": MODEL_IDS.get(model_key), "model_reported": None,
               "mode": MODE, "source": "none", "outcome": "error", "route": None, "evidence_ids": [],
               "provider_id": None, "source_call_id": None, "usage": None, "attempts": [],
               "live_attempts": 0, "request_sha256": None, "output_sha256": None, "cache_write_error": None}
    try:
        if route is not None and (not isinstance(route, str) or not route.strip()):
            raise ValueError("route must be a nonempty identifier or None")
        if (not isinstance(evidence_ids, (list, tuple))
                or any(not isinstance(item, str) or not item.strip() for item in evidence_ids)):
            raise ValueError("evidence_ids must be a list/tuple of nonempty identifiers")
        receipt.update(route=route, evidence_ids=list(evidence_ids))
        if MODE == "off":
            receipt.update(source="disabled", outcome="off")
            raise GeminiOff(feature)
        if MODE not in ("live", "replay"):
            raise ValueError("GEMINI_MODE must be off, replay or live")
        model = MODEL_IDS[model_key]
        f = _cache_file(model_key, input, thinking, config)
        receipt["request_sha256"] = f.stem
        if MODE == "replay" and f.exists():
            receipt["source"] = "cache"
            with f.open(encoding="utf-8", newline="") as stream:
                text = stream.read()
            origin = _cache_origin(f, text)
            receipt.update(source="cache", outcome="ok", source_call_id=origin.get("id"),
                           output_sha256=hashlib.sha256(text.encode()).hexdigest())
            # Provider/usage belong to the original live call, never to this replay invocation.
            receipt["cache_origin"] = {key: origin.get(key) for key in
                                       ("id", "provider_id", "model_requested", "model_reported", "usage")}
        else:
            receipt["source"] = "live"
            for attempt in range(3):
                count_call(feature)  # every real attempt, including retries, consumes the cap
                item = {"attempt": attempt + 1, "sdk_called": False, "outcome": "error", "error_type": None}
                receipt["attempts"].append(item)
                try:
                    client = _c()
                    item["sdk_called"] = True
                    receipt["live_attempts"] += 1
                    response = client.interactions.create(model=model, input=input,
                        generation_config={"thinking_level": thinking, **config})
                    item["outcome"] = "ok"
                    break
                except Exception as exc:
                    item["error_type"] = type(exc).__name__
                    if attempt == 2 or not any(code in str(exc) for code in RETRY_ON):
                        raise
                    time.sleep(2 ** attempt)
            text = response.output_text or ""
            provider_id, reported_model = getattr(response, "id", None), getattr(response, "model", None)
            receipt.update(outcome="ok", provider_id=provider_id if isinstance(provider_id, str) else None,
                           model_reported=reported_model if isinstance(reported_model, str) else None, usage=_usage(response),
                           output_sha256=hashlib.sha256(text.encode()).hexdigest())
            try:
                _atomic_write(f, text)
                origin = {key: receipt[key] for key in
                          ("id", "source", "provider_id", "model_requested", "model_reported", "usage", "output_sha256")}
                _atomic_write(f.with_suffix(".receipt.json"), json.dumps(origin, allow_nan=False))
            except OSError as exc:
                # A successful provider call is not retried or hidden by a local cache failure.
                receipt["cache_write_error"] = type(exc).__name__
    except Exception as exc:
        if isinstance(exc, GeminiCap):
            receipt["outcome"] = "cap_reached"
        receipt["error_type"] = type(exc).__name__  # never persist exception text (may contain input/keys)
        receipt["elapsed_ms"] = round(1000 * (time.perf_counter() - began), 3)
        with _lock:
            _receipts.append(deepcopy(receipt))
        exc.gemini_receipt = deepcopy(receipt)
        raise
    receipt["elapsed_ms"] = round(1000 * (time.perf_counter() - began), 3)
    with _lock:
        _receipts.append(deepcopy(receipt))
    return AskResult(text, deepcopy(receipt))


def er(input, thinking="high", feature="spatial_inspection", **config):
    """Embodied-reasoning text through the same cap, cache and receipts; never a movement permit."""
    return ask("embodied_reasoning", input, thinking=thinking, feature=feature, **config)


def mark_stand_in(feature):
    stand_ins.add(feature)


def status():
    """The status/gemini message body, published every 2 s by the hub."""
    with _lock:
        now = time.time()
        calls = sum(1 for t in _calls if now - t < 3600)
    return {"mode": MODE, "calls_last_hour": calls, "stand_ins": sorted(stand_ins)}
