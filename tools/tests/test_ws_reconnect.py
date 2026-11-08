"""WS-RECONNECT-TEST: a console that drops its /ws link and reconnects misses nothing and sees nothing twice.

Real Uvicorn hub on a real localhost socket (not the ASGI TestClient), the actual coord.hub gateway and
Bus, and a stand-in lane that publishes numbered `log/decision` events (`reason` is the sequence number).
A witness browser stays connected throughout; a reader browser drops its TCP connection without a close
handshake (as a closed laptop lid or lost Wi-Fi does) and reconnects. Checked:

- replay is capped at the latest 200 events, and replay then live is contiguous: no gap, no duplicate
  at the replay/live boundary (Bus.connect is atomic with delivery);
- a short outage loses nothing: the replay covers every event published while the reader was gone;
- dead clients are pruned from Bus.clients and do not disturb the witness's stream;
- after reconnecting, the reader's gate/answer and operator/command reach local subscribers and other
  browsers.

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

CAP = 200


class NumberedLane:
    """Publishes log/decision #0, #1, ... while `seq < target`; the test moves `target` from its thread."""

    def __init__(self):
        self.seq = 0
        self.target = 0
        self.answers = []
        self.commands = []

    async def pump(self, bus):
        while True:
            while self.seq < self.target:
                await bus.publish("log/decision", {"t": 0, "perception": "ws-reconnect stand-in",
                    "model": "none", "physics": "not a physics run", "outcome": "event",
                    "reason": str(self.seq)})
                self.seq += 1
                await asyncio.sleep(0.001)
            await asyncio.sleep(0.005)

    async def start(self, bus):
        bus.subscribe("gate/answer", self.answers.append)
        bus.subscribe("operator/command", self.commands.append)
        self.task = asyncio.create_task(self.pump(bus))
        return self.task


@pytest.fixture
def served(monkeypatch):
    """Start the hub with only the numbered lane (and no Gemini status publisher) on a free port."""
    target, lane = hub.Bus(), NumberedLane()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ("ws_reconnect_lane",))
    original_import = hub.importlib.import_module

    def imports(name):
        if name == "ws_reconnect_lane":
            return SimpleNamespace(start=lane.start)
        if name == "coord.gem":  # its 2 s status/gemini events would interleave with the numbered ones
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
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "hub failed to start"
        yield SimpleNamespace(port=port, bus=target, lane=lane)
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
    assert not worker.is_alive() and not target.clients


def connect(port):
    return ws_client.connect(f"ws://127.0.0.1:{port}/ws", proxy=None, open_timeout=10, close_timeout=2)


async def until(predicate, what, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.005)


class Browser:
    """Reads one connection in the background, keeping event numbers and every other message."""

    def __init__(self, conn):
        self.conn, self.seqs, self.other = conn, [], []
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.conn:
            message = json.loads(raw)
            if message["topic"] == "log/decision":
                self.seqs.append(int(message["data"]["reason"]))
            else:
                self.other.append(message)

    def drop(self):
        """Lose the link: abort the TCP connection, no close frame."""
        self.conn.transport.abort()
        self.task.cancel()


def contiguous(seqs):
    return seqs == list(range(seqs[0], seqs[0] + len(seqs))) if seqs else True


async def await_count(lane, n):
    await until(lambda: lane.seq >= n, f"{n} events published")


def test_reconnect_replays_capped_history_contiguously_with_no_loss_or_duplicates(served):
    lane, bus = served.lane, served.bus

    async def scenario():
        lane.target = 250  # overflow the 200-slot history before anyone connects
        await await_count(lane, 250)
        async with connect(served.port) as witness_conn, connect(served.port) as reader_conn:
            witness, reader = Browser(witness_conn), Browser(reader_conn)
            await until(lambda: len(reader.seqs) >= CAP and len(witness.seqs) >= CAP, "first replay")
            assert reader.seqs == list(range(250 - CAP, 250)), "replay must be exactly the latest 200"
            await until(lambda: len(bus.clients) == 2, "both browsers registered")

            # live traffic, then the reader's link dies mid-stream
            lane.target = 10**9
            await until(lambda: len(reader.seqs) >= CAP + 150, "live events on the reader")
            reader.drop()
            last_seen = reader.seqs[-1]
            await until(lambda: len(bus.clients) == 1, "the dead reader pruned from Bus.clients")

            # a short outage: well under 200 events published while the reader is gone
            lane.target = lane.seq + 60
            await await_count(lane, lane.target)
            gone_until = lane.seq
            assert gone_until - last_seen < CAP

            async with connect(served.port) as back_conn:
                back = Browser(back_conn)
                await until(lambda: back.seqs and back.seqs[-1] == gone_until - 1, "second replay")
                assert len(back.seqs) == CAP and back.seqs == list(range(gone_until - CAP, gone_until))
                assert back.seqs[0] <= last_seen + 1, "events published during the outage were lost"
                merged = sorted(set(reader.seqs) | set(back.seqs))
                assert contiguous(merged) and merged[-1] == gone_until - 1

                # resume live publishing: the replay/live boundary must have no gap and no repeat
                lane.target = 10**9
                await until(lambda: len(back.seqs) >= CAP + 300, "live events after reconnect")
                assert contiguous(back.seqs), "gap or duplicate across replay/live after reconnect"
                await until(lambda: len(bus.clients) == 2, "reader registered again")

                # the reconnected console can still answer gates and type commands
                answer = {"id": "g-after-reconnect", "approved": True, "by": "operator"}
                command = {"text": "send water to c1", "source": "typed"}
                await back_conn.send(json.dumps({"topic": "gate/answer", "data": answer}))
                await back_conn.send(json.dumps({"topic": "operator/command", "data": command}))
                await until(lambda: lane.answers == [answer] and lane.commands == [command],
                            "browser messages at the local subscribers")
                echoed = [{"topic": "gate/answer", "data": answer},
                          {"topic": "operator/command", "data": command}]
                await until(lambda: witness.other == echoed and back.other == echoed,
                            "browser messages forwarded to every browser")
                lane.target = lane.seq
                back.task.cancel()

            await until(lambda: len(bus.clients) == 1, "closed reader removed")
            await asyncio.sleep(0.05)
            # the witness never lost or repeated an event while the reader dropped and came back
            assert witness.seqs[0] == 250 - CAP and contiguous(witness.seqs)
            assert witness.seqs[-1] == lane.seq - 1
            assert len(bus.history) == CAP
            witness.task.cancel()

    asyncio.run(scenario())


def test_long_outage_replays_only_the_latest_200(served):
    lane, bus = served.lane, served.bus

    async def scenario():
        async with connect(served.port) as first_conn:
            first = Browser(first_conn)
            lane.target = 40
            await until(lambda: len(first.seqs) == 40, "events before the outage")
            first.drop()
            await until(lambda: not bus.clients, "the dead client pruned")
        lane.target = 40 + 500  # far more than history holds
        await await_count(lane, lane.target)
        async with connect(served.port) as back_conn:
            back = Browser(back_conn)
            await until(lambda: len(back.seqs) == CAP, "capped replay")
            await asyncio.sleep(0.1)
            # exactly the newest 200, no older ones, nothing extra (the history cap holds)
            assert back.seqs == list(range(lane.seq - CAP, lane.seq))
            back.task.cancel()

    asyncio.run(scenario())


def test_many_dead_clients_are_pruned_without_stalling_delivery(served):
    lane, bus = served.lane, served.bus

    async def scenario():
        lane.target = 10**9
        async with connect(served.port) as witness_conn:
            witness = Browser(witness_conn)
            dead = []
            for _ in range(20):
                conn = await connect(served.port)
                dead.append(Browser(conn))
            await until(lambda: len(bus.clients) == 21, "21 connected clients")
            for browser in dead:
                browser.drop()
            await until(lambda: len(bus.clients) == 1, "all 20 dead clients pruned", timeout=5)
            before = len(witness.seqs)
            await until(lambda: len(witness.seqs) >= before + 200, "delivery continues to the witness")
            lane.target = lane.seq
            await asyncio.sleep(0.05)
            assert contiguous(witness.seqs) and witness.seqs[-1] == lane.seq - 1
            assert len(bus.history) == CAP
            witness.task.cancel()

    asyncio.run(scenario())
