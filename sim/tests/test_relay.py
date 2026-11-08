"""L3 checks: breadcrumb relays keep the Scout's data flowing, heal around a lost relay, and buffer
while cut off."""

import asyncio
import itertools

import numpy as np

import sim
from hw import bridge, relay
from sim.world import World


def wall_at(*xs):
    """Synthetic building: a wall across the corridor at each x in xs."""
    def walls(a, b):
        lo, hi = sorted((a[0], b[0]))
        return sum(lo < x < hi for x in xs)
    return walls


# A tighter radio than the default so a short synthetic corridor is enough: 72 dB margin at 1 m, and
# one wall (60 dB) takes a 2 m link below the drop threshold.
TIGHT = relay.RadioSpec(sensitivity_dbm=-90.0, wall_db=60.0)


def make(walls, **kw):
    return relay.Relay(base=(0, 0, 0.1), walls=walls, spec=TIGHT, **kw)


def drive(r, xs, t0=0.0):
    events, t = [], t0
    for x in xs:
        events += r.step(t, (x, 0.0, 0.1))
        t += 0.5
    return events, t


def test_link_margin_falls_with_distance_and_walls():
    r = relay.Relay(base=(0, 0, 0.1), walls=wall_at(3.0))
    r.nodes["scout"] = (1.0, 0.0, 0.1)
    near = r.margin_db("scout", "base")
    r.nodes["scout"] = (2.9, 0.0, 0.1)
    far = r.margin_db("scout", "base")
    r.nodes["scout"] = (3.1, 0.0, 0.1)
    walled = r.margin_db("scout", "base")
    assert near > far > walled + 20
    assert r.spec.notes["tx_dbm"].startswith("source")


def test_scout_drops_crumbs_as_it_goes_and_stays_online():
    r = make(wall_at(2.0, 4.0, 6.0))
    events, _ = drive(r, np.arange(0.1, 6.5, 0.25))  # never exactly on a wall
    assert events == [("status/link", {"online": True})]
    xs = [r.nodes[n][0] for n in r.status()["relays"]]
    assert len(xs) >= 3 and 1.5 < xs[0] < 2.0  # first crumb just before the first wall, link still good
    assert xs == sorted(xs)
    bare = make(wall_at(2.0, 4.0, 6.0), crumbs=0)
    assert drive(bare, np.arange(0.1, 6.5, 0.25))[0][-1] == ("status/link", {"online": False})
    assert r.path[0] == "scout" and r.path[-1] == "base"
    delivered = sum(len(r.send(k)) for k in range(50))
    assert delivered >= 45


def test_running_out_of_crumbs_cuts_the_link_and_buffers():
    r = make(wall_at(2.0, 4.0), crumbs=1)
    events, _ = drive(r, np.arange(0.0, 7.5, 0.25))
    assert events[-1] == ("status/link", {"online": False})
    assert all(r.send(k) == [] for k in range(5))
    assert r.status()["buffered"] == 5


def test_store_and_forward_delivers_in_order_when_the_link_returns():
    r = make(wall_at(2.0), crumbs=0)
    drive(r, [0.0, 1.0, 5.0])  # past the wall with no relay to drop: cut off
    assert r.online is False
    for k in range(4):
        r.send(k)
    events = r.step(10.0, (1.0, 0.0, 0.1))  # back on the near side
    assert events == [("status/link", {"online": True})]
    assert r.flush() == [0, 1, 2, 3]


def test_chain_heals_around_a_lost_relay():
    r = make(wall_at(2.0, 4.0))
    drive(r, np.arange(0.0, 5.0, 0.25))
    assert set(r.status()["relays"]) == {"relay1", "relay2"}
    # Losing relay1 cuts the chain: relay2 cannot reach the base through two walls.
    assert r.fail("relay1", 6.0) == [("status/link", {"online": False})]
    # A relay in the open is not needed; losing it changes nothing.
    r2 = make(wall_at(4.0))
    drive(r2, np.arange(0.0, 4.5, 0.25))
    r2.nodes["relay9"] = (1.0, 0.0, 0.1)
    path_before = r2.route()
    assert r2.fail("relay9", 7.0) == [] and r2.route() == path_before
    assert r2.fail("base") == [] and r2.fail("nope") == []


def test_lossy_hop_loses_packets_but_retries_them_later():
    r = relay.Relay(base=(0, 0, 0.1), walls=wall_at(), seed=3)
    # Put the Scout where one try gets through about half the time.
    x = 0.0
    while r.best_margin((x, 0, 0.1)) > 0.5:
        x += 0.05
    r.nodes["scout"] = (x, 0.0, 0.1)
    r.path = r.route()
    got = []
    for k in range(200):
        got += r.send(k)
    for _ in range(20):
        got += r.flush()
    assert r.stats["lost_hops"] > 0
    assert sorted(got) == list(range(200))  # nothing lost for good


def test_relay_transport_reaches_the_hub_link():
    async def run():
        sent = []

        class Bus:
            async def publish(self, topic, data):
                sent.append(topic)

        inner = bridge.LoopbackTransport()
        r = relay.Relay(base=(0, 0, 0.1), walls=wall_at())
        r.step(0.0, (1.0, 0.0, 0.1))
        tr = relay.RelayTransport(inner, r)
        bridge.HubLink(tr, Bus())
        bridge.RobotSource(tr).send("sensors/scout", {"t": 0})
        await asyncio.sleep(0)
        return sent

    assert asyncio.run(run()) == ["sensors/scout"]


def test_real_scene_needs_a_relay_to_reach_the_back_room():
    w = World(render=False)
    path = [(-0.5, -1.5), (-0.5, -0.6), (-0.9, 0.25), (-0.2, 0.25), (0.6, 0.6), (1.25, 0.6), (1.8, 0.9)]

    def walk(r):
        for a, b in itertools.pairwise(path):
            for f in np.linspace(0, 1, 10):
                r.step(0.0, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 0.075))
        return r

    with_crumbs = walk(relay.Relay(base=w.pos, walls=sim._walls(w)))
    assert with_crumbs.online and with_crumbs.status()["relays"]
    without = walk(relay.Relay(base=w.pos, walls=sim._walls(w), crumbs=0))
    assert without.online is False


def test_sim_lane_routes_sensors_through_the_relay(monkeypatch):
    monkeypatch.setenv("AFTERSHOCK_HW", "1")
    monkeypatch.setenv("AFTERSHOCK_RELAY", "1")
    monkeypatch.setenv("AFTERSHOCK_BRIDGE", "loopback")
    got = []

    class Bus:
        def subscribe(self, topic, fn):
            pass

        async def publish(self, topic, data):
            got.append((topic, data))

    async def go():
        bus = Bus()
        world = await sim.start(bus, loop=False)
        task = asyncio.create_task(sim.run(world, bus))
        await asyncio.sleep(1.5)
        task.cancel()
        return world

    world = asyncio.run(go())
    assert world.relay is not None
    assert ("status/link", {"online": True}) in got
    assert any(topic == "sensors/scout" for topic, _ in got)
