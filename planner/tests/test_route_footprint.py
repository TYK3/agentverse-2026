"""Routes around corners must be drivable with the unchanged MuJoCo collision guard."""

import asyncio

import pytest

from planner.route import find_route


@pytest.mark.parametrize("obstacles", [
    {(x, y) for x in range(12, 17) for y in range(10, 16)},
    {(x, 15) for x in range(9, 21)} | {(9, y) for y in range(10, 16)},
])
def test_planned_corner_detour_clears_the_real_responder_guard(obstacles):
    room = {"res": .05, "cells": [
        {"cell": [x, y, 0], "state": "seen", "occupied": (x, y) in obstacles}
        for x in range(30) for y in range(30)
    ]}
    _drive(room, (3, 3, 0), (27, 27, 0))


@pytest.mark.parametrize("width", [6, 7, 8])
def test_right_angle_corridor_keeps_clearance_before_turning(width):
    def free(x, y):
        return (0 <= x <= 30 and 0 <= y < width
                or 31-width <= x <= 30 and 0 <= y <= 30)

    room = {"res": .05, "cells": [
        {"cell": [x, y, 0], "state": "seen", "occupied": not free(x, y)}
        for x in range(-1, 32) for y in range(-1, 32)
        if free(x, y) or any(free(x+dx, y+dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    ]}
    _drive(room, (3, width//2, 0), (26, 24, 0))


def test_handoff_selects_a_drivable_stopping_cell_outside_the_casualty_body():
    from planner.tests.test_handoff import World, casualty

    async def scenario():
        world = await World().start(start_cell=(3, 3, 0), occupied={
            (x, y) for x in range(29, 32) for y in range(29, 32)
        })
        goal = world.handoff.goal_for(casualty(pos=(1.5, 1.5, .1)))
        assert goal is not None
        _drive(world.router.map_cells, (3, 3, 0), goal)

    asyncio.run(scenario())


def _drive(room, start, goal):
    mujoco = pytest.importorskip("mujoco")
    from sim.responder import Responder, cell_centre

    result = find_route(room, [], start, goal)
    assert result["status"] == "ok", "open floor around both ends of the obstacle allows a detour"
    obstacles = [c["cell"][:2] for c in room["cells"] if c["occupied"]]
    walls = "".join(
        f'<body name="obstacle_{n}"><geom type="box" pos="{(x+.5)*.05} {(y+.5)*.05} .06" '
        'size=".025 .025 .06"/></body>' for n, (x, y) in enumerate(sorted(obstacles))
    )
    model = mujoco.MjModel.from_xml_string(
        '<mujoco><worldbody>' + walls
        + f'<body name="responder" mocap="true" pos="{(start[0]+.5)*.05} {(start[1]+.5)*.05} .05">'
        '<geom type="box" size=".16 .07 .05"/></body></worldbody></mujoco>'
    )
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    robot = Responder(model, data)
    robot.on_route({"id": "corner", "cells": result["cells"]})
    robot.move("corner")
    for _ in range(2000):
        robot.step(.02)
        if robot.state != "moving":
            break
    assert robot.state == "arrived", (robot.pos.tolist(), robot.log[-1])
    assert robot.pos[:2] == pytest.approx(cell_centre(goal), abs=.005)
