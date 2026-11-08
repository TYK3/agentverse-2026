"""Show the scripted aftershock in the MuJoCo viewer and print the blocks it moves (T05).

    python -m sim.demo_aftershock              # viewer; shake starts after 2 s
    python -m sim.demo_aftershock --no-viewer  # headless, prints the same result
    python -m sim.demo_aftershock --scene tower   # the collapsed tower (ref Y1)

Before the shake it prints which blocks the physics check predicts will move; after it, the
world/change message the live run produces.
"""

import argparse
import time

from sim import aftershock, scene
from sim.world import World


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-viewer", action="store_true")
    p.add_argument("--scene", default="backup", help="backup (default) or tower")
    p.add_argument("--delay", type=float, default=2.0, help="seconds before the shake")
    a = p.parse_args()

    world = World(path=scene.resolve(a.scene)[1], render=False)
    print(f"predicted by the physics check on a copy: {world.would_move}")
    viewer = None
    if not a.no_viewer:
        import mujoco.viewer

        viewer = mujoco.viewer.launch_passive(world.m, world.d)
    dt, end = 0.02, a.delay + aftershock.DURATION + 2.0
    change = None
    while world.t < end and (viewer is None or viewer.is_running()):
        started = time.monotonic()
        if world.t >= a.delay and change is None and not world.shaking:
            world.trigger_aftershock()
            print(f"t={world.t:.1f}s aftershock: {aftershock.AMPLITUDE} m at {aftershock.FREQ} Hz for {aftershock.SHAKE} s")
        for topic, data in world.tick(dt):
            change = data
            print(f"t={world.t:.1f}s {topic} {data}")
        if viewer is not None:
            viewer.sync()
            time.sleep(max(0.0, dt - (time.monotonic() - started)))
    if viewer is not None:
        viewer.close()
    print(f"moved blocks: {change['moved_blocks'] if change else 'none (stopped early)'}")


if __name__ == "__main__":
    main()
