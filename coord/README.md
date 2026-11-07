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
then return; they may return a task or list of tasks for shutdown cancellation.
Missing packages or start hooks are logged and skipped; broken installed dependencies
raise rather than silently disabling a lane. Subscriber exceptions are logged while
other subscribers continue.

The browser connects to `ws://localhost:8000/ws` using `{ "topic": "...", "data": ... }`.
Only `operator/command` and `gate/answer` may be sent from the browser. Invalid
messages close with code 1008 before dispatch. Arrays stay arrays. The latest 200
forwarded events are replayed in order. This event history is not a map snapshot;
perception supplies periodic full snapshots. `sensors/scout` goes only to local
subscribers and is never retained or forwarded to browsers.

`fixtures/*.json` are development examples, not observations from a live run.
There is one full envelope for each schema in `messages.TOPICS`. The optional
`coord.gem` publisher emits its status every two seconds without making model calls.
