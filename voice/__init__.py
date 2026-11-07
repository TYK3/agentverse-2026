"""voice lane: operator voice commands (T21), spoken guidance and translation (T22).

- voice/typed.py     typed twin: stdin lines -> operator/command {"text", "source": "typed"}
- voice/operator.py  push-to-talk microphone -> gemini-3.8-live -> operator/command {"source": "voice"}
- voice/intent.py    intents and the change-of-mind resolution both share
"""
