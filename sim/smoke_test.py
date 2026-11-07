"""Check that MuJoCo works on this computer.

Run:  python sim/smoke_test.py
Optional: python sim/smoke_test.py path/to/mujoco_menagerie   (also loads the Franka arm)
"""
import os
import sys

import mujoco

XML = """<mujoco><worldbody><light pos="0 0 3"/><geom type="plane" size="2 2 .1"/>
<body pos="0 0 1"><freejoint/><geom type="box" size=".1 .1 .1" rgba="1 0 0 1"/></body></worldbody></mujoco>"""


def physics():
    m = mujoco.MjModel.from_xml_string(XML)
    d = mujoco.MjData(m)
    for _ in range(1000):
        mujoco.mj_step(m, d)
    print(f"physics ok: box rests at z={d.qpos[2]:.3f} (expect about 0.1)")


def render(m, d, w=160, h=120):
    r = mujoco.Renderer(m, h, w)
    mujoco.mj_forward(m, d)
    r.update_scene(d)
    return r.render()


def offscreen():
    m = mujoco.MjModel.from_xml_string(XML)
    d = mujoco.MjData(m)
    print("offscreen render ok:", render(m, d).shape)


def franka(menagerie):
    path = os.path.join(menagerie, "franka_emika_panda", "scene.xml")
    m = mujoco.MjModel.from_xml_path(path)
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, 0)
    for _ in range(500):
        mujoco.mj_step(m, d)
    print(f"franka ok: {m.nbody} bodies, {m.nu} actuators, simulated {d.time:.1f}s")


if __name__ == "__main__":
    print("mujoco", mujoco.__version__)
    physics()
    offscreen()
    if len(sys.argv) > 1:
        franka(sys.argv[1])
    print("For the live window run: python -m mujoco.viewer")
