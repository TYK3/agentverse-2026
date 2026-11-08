"""Shared by the typed twin and the live voice session: resolve, log, publish operator/command.

Until the hub (T02, coord/hub.py) lands, `StdoutBus` stands in for it: each message is printed as one
line `operator/command {"text": ..., "source": ...}` so it can be piped or read by eye.
"""

import datetime
import json
import os
import pathlib
import sys

from voice import intent as intents

TOPIC = "operator/command"
LOG = pathlib.Path(os.environ.get("VOICE_LOG", pathlib.Path(__file__).resolve().parent / "logs" / "transcript.jsonl"))


class StdoutBus:
    """Prints each message as `topic json` on stdout. Same publish() shape as the hub's bus."""

    def __init__(self, out=None):
        self.out = out or sys.stdout

    async def publish(self, topic, data):
        print(topic, json.dumps(data), file=self.out, flush=True)


def log(entry, path=None):
    """Append one transcript line (JSON) with a UTC timestamp."""
    path = pathlib.Path(path or LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": datetime.datetime.now(datetime.UTC).isoformat(), **entry}) + "\n")


async def publish(bus, heard, intent, source, how, log_path=None):
    """Publish operator/command for an intent; log it either way. Returns the message, or None if not understood."""
    text = intents.to_text(intent)
    msg = {"text": text, "source": source} if text else None
    log({"source": source, "heard": heard, "intent": intent, "resolved_by": how, "published": msg}, log_path)
    if msg:
        await bus.publish(TOPIC, msg)
    return msg
