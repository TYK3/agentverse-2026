"""T15: the edge budget meter. Publishes status/budget every second.

mem_mb is the planner process RSS plus what the local runtime holds for the loaded model (the model
lives in the Ollama process, so counting only the planner would hide most of the cost).
ms_per_step is the slowest planner step in the last window. Device and limits: planner/budget.json.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from planner import local_llm

CONFIG = json.loads((Path(__file__).parent / "budget.json").read_text(encoding="utf-8"))


def rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except ImportError:  # Linux fallback without psutil
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1e6


class Budget:
    def __init__(self, bus, *, config=CONFIG, model_mb=local_llm.loaded_mb, clock=time.perf_counter):
        self.bus, self.config, self.model_mb, self.clock = bus, config, model_mb, clock
        self.steps: list[float] = []
        self.last_ms = 0.0

    @contextlib.contextmanager
    def step(self):
        """`with budget.step():` around one planner step (propose, gate, re-plan)."""
        t = self.clock()
        try:
            yield
        finally:
            self.steps.append((self.clock() - t) * 1000)

    def message(self) -> dict:
        if self.steps:
            self.last_ms, self.steps = max(self.steps), []
        model_mb = self.model_mb()
        model = self.config["model"] if model_mb else self.config["model"] + " (not loaded)"
        return {"device": self.config["device"], "mem_mb": round(rss_mb() + model_mb, 1),
                "model": model, "ms_per_step": round(self.last_ms, 1),
                "limit": self.config["limit"]}

    def within(self, msg: dict) -> bool:
        lim = msg["limit"]
        return msg["mem_mb"] <= lim["mem_mb"] and msg["ms_per_step"] <= lim["ms_per_step"]

    async def run(self, interval=1.0):
        while True:
            await self.bus.publish("status/budget", await asyncio.to_thread(self.message))
            await asyncio.sleep(interval)
