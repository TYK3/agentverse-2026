"""Typed twin of the voice command: one stdin line in, one operator/command out (source "typed").

    python -m voice.typed            # type "send water to the left room, no, the back room"
    echo "scan the kitchen" | python -m voice.typed

Change-of-mind is resolved locally (voice/intent.py), so the planner only ever sees the final command.
This is a real feature (audio can fail on the day), not a Gemini stand-in.
"""

import asyncio
import sys

from voice import command
from voice import intent as intents


async def handle(bus, line, log_path=None):
    """Resolve one typed line and publish it. Returns the message, or None if it was not understood."""
    line = line.strip()
    if not line:
        return None
    msg = await command.publish(bus, line, intents.parse(line), "typed", "local parser", log_path)
    if msg is None:
        print(f"not understood: {line!r} (try: send water to the back room / scan the left room / stop)",
              file=sys.stderr, flush=True)
    return msg


async def run(bus, lines, log_path=None):
    for line in lines:
        await handle(bus, line, log_path)


def main():
    if sys.stdin.isatty():
        print("typed commands (Ctrl+D to quit):", file=sys.stderr, flush=True)
    asyncio.run(run(command.StdoutBus(), sys.stdin))


if __name__ == "__main__":
    main()
