"""Check that the Gemini key works and each model ID answers.

Run:  python tools/gemini_ping.py gemini-4-argon gemini-3.8-flash
Needs GEMINI_API_KEY in .env (never commit it). One person running this is enough; it spends calls.
This is the only place a bare genai.Client() is used; product code calls Gemini through coord/gem.py.
"""
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client()  # reads GEMINI_API_KEY
for model in sys.argv[1:] or ["gemini-4-argon", "gemini-3.8-flash"]:
    r = client.interactions.create(model=model, input="Reply with the single word: ready",
                                   generation_config={"thinking_level": "low"})
    print(model, "->", r.output_text)
