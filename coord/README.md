# Shared message hub

Install the shared root requirements when T01 (#9) lands. For transport tests alone:

```sh
python -m pip install -r coord/requirements.txt
GEMINI_MODE=off python -m pytest coord/tests -q
uvicorn coord.hub:app --port 8000 --reload
curl -i http://localhost:8000/docs
```

Lanes expose `async def start(bus)`, subscribe with `bus.subscribe(topic, callback)`,
and publish with `await bus.publish(topic, data)`. Callbacks receive validated JSON
data and may be sync or async. Startup functions wire subscriptions and launch work,
then return; they may return a task, list of tasks, or object with `.task` for
shutdown cancellation.
Missing packages or start hooks are logged and skipped; broken installed dependencies
raise rather than silently disabling a lane. Subscriber exceptions are logged while
other subscribers continue.

The hub starts D1's measured point publisher alongside the lanes. It projects
only Scout depth `points` and optional `points_from` to browser-read-only
`map/points {t,res,points,points_from?}`. At most 2048 measured points are kept per
frame, with actual xyz preserved (including basement heights), deduplicated on
a 0.05 m voxel grid. The newest pending frame is sent at most twice per second.
Missing/null points do nothing; an explicit empty batch clears the cloud.
The source timestamp is preserved when present; recordings without one use
elapsed time since publisher startup. No image, thermal or acoustic data is copied.

The browser connects to `ws://localhost:8000/ws` using `{ "topic": "...", "data": ... }`.
Only `operator/command`, `gate/answer` and the offline toggle `status/link` may be sent from the browser. Invalid
messages close with code 1008 before dispatch. Arrays stay arrays. The latest 200
forwarded events are replayed in order. Point frames use a separate latest-only
slot: new clients receive only the newest cloud after the event replay, without
point traffic evicting logs or permits. Scene changes clear pending/reconnect
clouds. This event history is not a map snapshot;
perception supplies periodic full snapshots. `sensors/scout` goes only to local
subscribers and is never retained or forwarded to browsers.

`fixtures/*.json` are development examples, not observations from a live run.
There is one full envelope for each schema in `messages.TOPICS`. The optional
`coord.gem` publisher emits its status every two seconds without making model calls.

## AFTERLIGHT Gemini call receipts (G1)

`gem.ask(...)` still returns text. `gem.ask_with_receipt(...)` returns an
`AskResult` with `.text` and `.receipt`. `gem.er(...)` selects
`MODEL_IDS["embodied_reasoning"]` (`gemini-robotics-er-2-preview`) through that same
door. Receipt route linkage is local metadata, never a request to the provider:

```python
result = gem.ask_with_receipt("embodied_reasoning", image_and_prompt,
    feature="spatial_inspection", route="r3", evidence_ids=["scan-42"])
text, call_id = result.text, result.receipt["id"]
```

Each invocation has a unique `gem-...` ID, timestamp, requested/reported model,
mode, source (`live`, `cache`, `disabled`, or `none`), outcome, provider ID,
attempt list, available provider token usage and elapsed milliseconds. `route`
matches `permit/route.route`; `evidence_ids` reference caller-owned observations.
No permit schema changes are made. A Gemini receipt never grants movement.

Replay gets a new ID, zero live attempts and no current provider usage. Its
`source_call_id` and `cache_origin` attribute the original live call only when
the cached output hash matches its sidecar; legacy or corrupt metadata stays
unattributed. Missing token usage is null, never an invented zero. Every SDK
retry consumes the live cap. Cache write errors do not retry a successful call.

Failures keep their original exceptions and attach `.gemini_receipt`.
`gem.receipts()` returns copies of the latest 200 completed invocations.
The hub forwards new entries as `gemini/receipt` on each two-second status poll,
deduplicated by invocation ID, and never calls a model to produce status/receipts.
The event is read-only for browser clients. Physics results join separately by route ID.
Prompts, images, output text and exception messages are excluded. Cache sidecars remain
under the ignored `.gem_cache/`; existing direct Live/session callers that only
use `count_call()` are counted but are not claimed as receipt-covered yet.

API references: [Interactions API](https://aistudio.google.com/docs/interactions-overview.md),
[usage fields](https://aistudio.google.com/api-reference/interactions-api.md),
[Robotics spatial reasoning](https://aistudio.google.com/docs/robotics-spatial.md).
