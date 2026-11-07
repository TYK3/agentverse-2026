"""Operator voice commands (T21): hold space, speak, release -> one operator/command (source "voice").

    GEMINI_MODE=live python -m voice.operator

Microphone audio (sounddevice, 16 kHz mono 16-bit PCM) streams into a gemini-3.8-live session only
while space is held (push-to-talk: automatic voice detection is off, we send activity_start/end, so
background noise cannot trigger a command). The model is told to return the FINAL intent only as JSON,
resolving changes of mind ("left room, no, the back room").

Falls back to the typed twin (voice/typed.py) when:
- GEMINI_MODE is off: a labelled stand-in, reported to coord/gem.py (replay makes real calls,
  since live audio cannot be replayed from a cache);
- there is no microphone or no sounddevice.
Push-to-talk uses pynput to see key release; without it (no display, e.g. WSL), press Enter to start
and Enter again to stop.
"""

import asyncio
import os
import sys

from voice import command, typed
from voice import intent as intents

FEATURE = "operator_voice"
RATE = 16000
CHUNK = RATE // 10  # 100 ms of audio per message
SYSTEM = (
    "You turn a rescue operator's spoken command for a Responder robot into one JSON object and say "
    "nothing else. Shape: {\"goal\": \"deliver\"|\"scan\"|\"stop\"|\"return\"|null, "
    "\"item\": \"water\"|\"first_aid_kit\"|\"radio\"|null, \"place\": \"<place, e.g. back room>\"|null}. "
    "If the speaker changes their mind (\"send water to the left room, no, the back room\"), return only "
    "the FINAL intent. If you cannot tell what they want, return {\"goal\": null, \"item\": null, \"place\": null}."
)


def _gem():
    """coord/gem.py once T26 merges; until then None and the mode comes from the environment."""
    try:
        from coord import gem
        return gem
    except ImportError:
        return None


def mode():
    gem = _gem()
    return gem.MODE if gem else os.environ.get("GEMINI_MODE", "off")


def model_id():
    gem = _gem()
    return gem.MODEL_IDS["live_voice_vision"] if gem else "gemini-3.8-live"


def stand_in(why):
    """Label the fallback on screen (stderr), in the transcript and in the gemini status badge."""
    gem = _gem()
    if gem:
        gem.mark_stand_in(FEATURE)
    print(f"[STAND-IN] operator voice is off ({why}); using the typed twin.", file=sys.stderr, flush=True)
    command.log({"source": "voice", "stand_in": True, "why": why})


async def handle_reply(bus, reply, heard, log_path=None):
    """Turn the live model's reply for one push-to-talk turn into operator/command."""
    try:
        intent = intents.from_model_json(reply)
        how = model_id()
    except ValueError as e:
        # The model's JSON was unusable; resolve what it heard with the local parser and say so in the log.
        print(f"model reply not usable ({e}); parsing the transcript locally", file=sys.stderr, flush=True)
        intent, how = intents.parse(heard or ""), "local parser on live transcript"
    msg = await command.publish(bus, heard, intent, "voice", how, log_path)
    print(f"heard: {heard!r} -> {msg['text'] if msg else 'not understood'}", file=sys.stderr, flush=True)
    return msg


class PushToTalk:
    """`down` is set while the talk key is held. Space with pynput; Enter toggles without it."""

    def __init__(self, loop):
        self.loop, self.down = loop, asyncio.Event()
        try:
            from pynput import keyboard
            def press(k):
                if k == keyboard.Key.space:
                    loop.call_soon_threadsafe(self.down.set)
            def release(k):
                if k == keyboard.Key.space:
                    loop.call_soon_threadsafe(self.down.clear)
            keyboard.Listener(on_press=press, on_release=release, daemon=True).start()
            self.hint = "hold SPACE to talk"
        except (ImportError, OSError):  # no pynput, or no display to listen on (pynput raises ImportError)
            loop.add_reader(sys.stdin, self._toggle)
            self.hint = "press ENTER to start talking, ENTER again to stop"

    def _toggle(self):
        sys.stdin.readline()
        self.down.clear() if self.down.is_set() else self.down.set()

    async def released(self):
        while self.down.is_set():
            await asyncio.sleep(0.02)


def open_mic(loop, queue):
    """Start a 16 kHz mono int16 input stream that puts raw PCM chunks on queue. Raises if no mic."""
    import sounddevice as sd  # OSError here when the PortAudio library is missing
    try:
        sd.check_input_settings(samplerate=RATE, channels=1, dtype="int16")
    except (sd.PortAudioError, ValueError) as e:  # no input device, or it cannot do 16 kHz mono
        raise OSError(str(e)) from e

    def callback(data, frames, time, status):
        loop.call_soon_threadsafe(queue.put_nowait, bytes(data))

    stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=callback)
    stream.start()
    return stream


async def turn(session, ptt, queue, types):
    """Stream one push-to-talk turn and return (model reply text, input transcription)."""
    while not queue.empty():
        queue.get_nowait()  # drop audio from before the key went down
    await session.send_realtime_input(activity_start=types.ActivityStart())
    released = asyncio.ensure_future(ptt.released())
    while not released.done():
        get = asyncio.ensure_future(queue.get())
        done, _ = await asyncio.wait({get, released}, return_when=asyncio.FIRST_COMPLETED)
        if get in done:
            await session.send_realtime_input(audio=types.Blob(data=get.result(), mime_type=f"audio/pcm;rate={RATE}"))
        else:
            get.cancel()
    await session.send_realtime_input(activity_end=types.ActivityEnd())
    reply, heard = "", ""
    async for msg in session.receive():
        sc = msg.server_content
        if sc and sc.input_transcription and sc.input_transcription.text:
            heard += sc.input_transcription.text
        reply += msg.text or ""
        if sc and sc.turn_complete:
            break
    return reply, heard.strip()


def gem_client(gem):
    """The google-genai client from coord/gem.py, so the key and .env stay behind the one door (POLICY #8)."""
    return gem.client() if hasattr(gem, "client") else gem._c()


async def live(bus, loop, queue, stream, gem):
    # config types only; the client comes from coord/gem.py
    from google.genai import types

    gem.count_call(FEATURE)  # one per session, against the shared cap
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        system_instruction=SYSTEM,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)),
    )
    ptt = PushToTalk(loop)
    print(f"operator voice live on {model_id()}: {ptt.hint} (Ctrl+C to quit)", file=sys.stderr, flush=True)
    try:
        async with gem_client(gem).aio.live.connect(model=model_id(), config=config) as session:
            while True:
                await ptt.down.wait()
                reply, heard = await turn(session, ptt, queue, types)
                await handle_reply(bus, reply, heard)
    finally:
        stream.stop()


async def run(bus):
    m = mode()
    if m not in ("live", "replay"):
        stand_in(f"GEMINI_MODE={m}")
        return await typed.run(bus, sys.stdin)
    gem = _gem()
    if gem is None:  # every product Gemini call goes through coord/gem.py: no gem, no live session
        stand_in("coord/gem.py is not available")
        return await typed.run(bus, sys.stdin)
    loop, queue = asyncio.get_running_loop(), asyncio.Queue()
    try:
        stream = open_mic(loop, queue)
    except (ImportError, OSError) as e:  # no sounddevice, no PortAudio or no input device
        stand_in(f"no microphone: {e}")
        return await typed.run(bus, sys.stdin)
    await live(bus, loop, queue, stream, gem)


def main():
    try:
        asyncio.run(run(command.StdoutBus()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
