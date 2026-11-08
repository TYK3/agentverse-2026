"""WS-SLOW-READER: one /ws browser that stays connected but stops reading must not stall the hub.

Coord.hub's Bus.publish awaits each browser's send_text while holding one delivery lock, and before it
runs local subscribers. If a browser's tab is frozen (backgrounded, debugger paused, overloaded laptop),
its TCP window closes and that send never completes. These tests put a real Uvicorn hub on localhost,
open one browser that never reads after the handshake, and check that within a few seconds:

- a healthy browser still receives new events;
- local subscribers (the planner, perception) still receive new events;
- new browsers can still connect and get their replay.

Synthetic events only: no sim, no physics, no model calls.
"""

import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")
ws_client = pytest.importorskip("websockets.asyncio.client")

from coord import hub

PAD = "x" * 4000  # ~4 KB events fill a stalled reader's socket buffers in a few hundred events
STALL_LIMIT_S = 3.0


class NumberedLane:
    def __init__(self):
        self.seq = 0
        self.running = False
        self.local = []  # event numbers a local subscriber saw

    async def pump(self, bus):
        while True:
            if self.running:
                await bus.publish("log/decision", {"t": 0, "perception": PAD, "model": "none",
                    "physics": "not a physics run", "outcome": "event", "reason": str(self.seq)})
                self.seq += 1
            await asyncio.sleep(0.002)

    async def start(self, bus):
        bus.subscribe("log/decision", lambda data: self.local.append(int(data["reason"])))
        self.task = asyncio.create_task(self.pump(bus))
        return self.task


@pytest.fixture
def served(monkeypatch):
    target, lane = hub.Bus(), NumberedLane()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ("ws_slow_lane",))
    original_import = hub.importlib.import_module

    def imports(name):
        if name == "ws_slow_lane":
            return SimpleNamespace(start=lane.start)
        if name == "coord.gem":
            raise ModuleNotFoundError(name="coord.gem")
        return original_import(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(64)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(hub.app, log_config=None, log_level="warning",
                                          access_log=False, lifespan="on"))
    worker = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[listener])), daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while not server.started and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "hub failed to start"
    try:
        yield SimpleNamespace(port=port, bus=target, lane=lane)
    finally:
        lane.running = False
        server.should_exit = True
        server.force_exit = True  # a stalled send may never finish on its own
        worker.join(timeout=10)
        listener.close()


def connect(port, **kw):
    return ws_client.connect(f"ws://127.0.0.1:{port}/ws", proxy=None, open_timeout=10,
                             close_timeout=1, max_size=2**22, **kw)


def frozen_tab(port):
    """A raw TCP client that completes the WebSocket handshake and then never reads again."""
    sock = socket.create_connection(("127.0.0.1", port))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    sock.sendall((f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                  "Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                  "Sec-WebSocket-Version: 13\r\n\r\n").encode())
    reply = b""
    while b"\r\n\r\n" not in reply:
        reply += sock.recv(1)
    assert reply.startswith(b"HTTP/1.1 101"), reply
    return sock


async def received_new(conn, after, timeout):
    """Read until an event numbered > after arrives; return it, or None on timeout."""
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            raw = await asyncio.wait_for(conn.recv(), remaining)
        except TimeoutError:
            return None
        message = json.loads(raw)
        if message["topic"] == "log/decision" and int(message["data"]["reason"]) > after:
            return int(message["data"]["reason"])
    return None


def stall_then(served, check):
    """Run events, freeze one tab, give its buffers time to fill, then run `check`."""
    lane = served.lane

    async def scenario():
        async with connect(served.port) as healthy:
            lane.running = True
            assert await received_new(healthy, -1, 5) is not None, "no events before the stall"
            frozen = frozen_tab(served.port)
            try:
                # Keep the healthy browser drained while the frozen tab's buffers fill.
                fill_until = time.monotonic() + 2.0
                while time.monotonic() < fill_until:
                    try:
                        await asyncio.wait_for(healthy.recv(), 0.2)
                    except TimeoutError:
                        pass
                await check(healthy)
            finally:
                frozen.close()

    asyncio.run(scenario())


def test_frozen_tab_does_not_stall_other_browsers(served):
    async def check(healthy):
        mark = served.lane.seq
        got = await received_new(healthy, mark, STALL_LIMIT_S)
        assert got is not None, (f"healthy browser got no new event for {STALL_LIMIT_S}s while one tab "
                                 f"is frozen (publisher stuck at #{served.lane.seq})")

    stall_then(served, check)


def test_frozen_tab_does_not_stall_local_subscribers(served):
    async def check(_healthy):
        before = len(served.lane.local)
        await asyncio.sleep(STALL_LIMIT_S)
        assert len(served.lane.local) > before, (f"planner/perception subscribers got no event for "
                                                 f"{STALL_LIMIT_S}s while one tab is frozen")

    stall_then(served, check)


def test_frozen_tab_does_not_block_new_connections(served):
    async def check(_healthy):
        async def join():
            async with connect(served.port) as late:
                return await received_new(late, -1, STALL_LIMIT_S)

        try:
            got = await asyncio.wait_for(join(), STALL_LIMIT_S + 2)
        except TimeoutError:
            got = None
        assert got is not None, "a new browser could not get its replay while one tab is frozen"

    stall_then(served, check)
