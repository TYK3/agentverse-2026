"""The Scout explores the real sim (sim/world.py) from the scene's own start outside the breach.

Regression for the #32 smoke run: from [-0.5, -1.5] the Explorer sent no scout/goto at all (its square
clearance closed the way in past rubble b12), then drove into spots sim refuses to move from.
"""

from perception.casualties import Casualties
from perception.explore import Explorer
from perception.grid import Grid
from perception.hazards import Hazards
from sim.world import World


def test_scout_enters_from_scene_start_and_finds_c1():
    w = World(seed=0, render=False)
    grid, cas = Grid(), Casualties(vision_on=False)
    explorer = Explorer(grid)
    hazards = Hazards(grid)                                  # scans only: no scene/loaded block poses (Z1)
    assert [round(v, 2) for v in w.pos[:2]] == [-0.5, -1.5]
    rooms, gotos = set(), 0
    for step in range(900):                                  # 90 s at 10 Hz, decisions at 1 Hz
        w.tick(0.1)
        data = w.sensors_message(camera=False)
        grid.add_sensors(data)
        explorer.on_sensors(data)
        cas.on_sensors(data)
        hazards.on_sensors(data)
        x, y = w.pos[:2]
        if -1.0 < y < 1.5:
            rooms.add(1 if x < 0 else 2 if x < 1.25 else 3)
        if step % 10 == 0 and (msg := hazards.update(w.t)) is not None:
            explorer.on_hazards(msg)
        if step % 10 == 0 and (goto := explorer.tick(w.t)):
            w.goto(goto)
            gotos += 1
    assert gotos > 10
    assert rooms == {1, 2, 3}, f"Scout only reached rooms {sorted(rooms)}"
    assert [c["id"] for c in cas.message()] == ["c1"]
