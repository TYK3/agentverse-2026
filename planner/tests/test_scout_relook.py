"""#31: permit re-looks must use reachable Scout waypoints and survive hub payload copies."""

import asyncio

from coord.hub import Bus
from perception.explore import Explorer
from perception.grid import Grid

Z = 0.075


def test_external_relook_across_a_wall_routes_through_seen_free_space():
    grid = Grid()
    for i in range(-16, 17):
        for j in range(-10, 31):
            grid.free((i, j, 1))
    for j in range(-10, 11):
        grid.hit((0, j, 1))
    explorer = Explorer(grid)
    explorer.on_sensors({"pose": {"pos": [0.325, 0.025, Z]}})
    request = {"target": [-0.325, 0.025, Z], "reason": "re-look to re-earn move permission on route r1"}
    assert not explorer._straight(request["target"])
    explorer.on_goto(request, 0)
    waypoint = explorer.tick(1)
    assert waypoint is not None, "the raw across-wall target must not leave the Scout held against a wall"
    assert waypoint["target"] != request["target"]
    assert explorer._straight(waypoint["target"])
    assert explorer._clear_ahead(waypoint["target"])
    assert "re-look" in waypoint["reason"]
    held_goal = explorer.hold
    asyncio.run(_echo(explorer, waypoint))
    assert explorer.hold == held_goal, "validated echo must retain the ultimate re-look goal"


async def _echo(explorer, waypoint):
    bus = Bus()
    bus.subscribe("scout/goto", lambda data: explorer.on_goto(data, 1))
    await bus.publish("scout/goto", waypoint)


def test_a_validated_echo_of_the_explorers_own_waypoint_does_not_create_a_hold():
    grid = Grid()
    for i in range(40):
        for j in range(-7, 8):
            grid.free((i, j, 1))
        grid.hit((i, -8, 1))
        grid.hit((i, 8, 1))
    for j in range(-8, 9):
        grid.hit((-1, j, 1))
    explorer = Explorer(grid)
    explorer.on_sensors({"pose": {"pos": [0.1, 0.025, Z]}})
    waypoint = explorer.tick(0)
    assert waypoint is not None and explorer.hold is None
    asyncio.run(_echo(explorer, waypoint))
    assert explorer.hold is None, "JSON validation copies dicts; identity cannot identify our own waypoint"
