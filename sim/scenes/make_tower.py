"""Generate sim/scenes/tower.xml, the collapsed tower scene (ref Y1).

    python -m sim.scenes.make_tower

A three-storey tower on a 4 m x 3 m footprint (x -2..2, y -1.5..1.5, z up, metres) after an earthquake.
The west part (x < 0.45) still stands three storeys; the east part has collapsed into the ground storey,
leaving two voids with people in them. Robots work on the ground storey only.

Plan of the ground storey (x to the right, y up):

    y=1.5  +==============================================+
           |  west room            ||   lean-to void (c2) |   c2: enclosed, found by sound only
           |                       door  =========/       |
           |   c1 (silent)         ||   closure H, G2     |   G2 is light: clearing it opens a view to c2
           |                       ||            LS_a  /  |   LS_a: loose slab leaning on the east wall
           |                       ||  pancake slab       |   c3: under the pancake, thermal + faint sound
           |                       ||  on piers (c3)  c4  |   c4: behind the breach rubble
    y=-1.5 +====== entrance ===========  breach (G1)  ====+
         x=-2   (x -0.6..0)        x=0.4  (x 1.2..1.7)   x=2

Above the west room: floor slab F1 (it juts 0.45 m over the east room as a broken ledge), storey-2
walls, floor slab F2, and the broken storey-3 west and north walls. LS_b is a loose slab standing on the
F1 ledge, leaning on the storey-2 east wall: the aftershock drops it into the east room.

Labels: wall (standing walls), slab (floors and the wedged void slabs), rubble (everything loose or
heaped). The structure, the void slabs and the piers are welded to the floor plate ("braced") so the
voids survive the shake; loose slabs and rubble are free.
"""

import os
import pathlib

OUT = pathlib.Path(__file__).parent / "tower.xml"
GAP = 0.005
H = 1.0          # storey height
T = 0.05         # half thickness of walls and floor slabs

WALL = "0.8 0.7 0.5 1"
WALL2 = "0.75 0.65 0.45 1"
SLAB = "0.6 0.6 0.62 1"
RUBBLE = "0.55 0.5 0.45 1"
LIGHT = "0.6 0.45 0.35 1"

blocks = []      # (name, label, xml body, braced)


def box(label, lo, hi, rgba, braced, mass=None, density=None, note=""):
    """An axis-aligned box from corner lo to corner hi."""
    c = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    s = [(b - a) / 2 for a, b in zip(lo, hi, strict=True)]
    return add(label, c, s, rgba, braced, mass=mass, density=density, note=note)


LOOSE_FRICTION = float(os.environ.get("TOWER_LOOSE_FRICTION", "0.4"))   # dusty broken concrete


def add(label, pos, size, rgba, braced, euler=None, mass=None, density=None, note="", friction=None):
    name = f"b{len(blocks) + 1}"
    rot = f' euler="{euler}"' if euler else ""
    m = f' mass="{mass}"' if mass else (f' density="{density}"' if density else "")
    if friction is not None:
        m += f' friction="{friction} 0.005 0.0001" priority="1"'  # priority: its friction wins at contacts
    f = lambda v: " ".join(f"{x:.4f}".rstrip("0").rstrip(".") for x in v)
    comment = f"   <!-- {note} -->" if note else ""
    xml = (f'    <body name="{name}" pos="{f(pos)}"{rot}><freejoint/>'
           f'<geom name="{name}_{label}" type="box" size="{f(size)}"{m} rgba="{rgba}"/></body>{comment}')
    blocks.append((name, label, xml, braced))
    return name


def storey_walls(z0, z1, rgba, which=("W", "N", "S", "E"), x_east=0.4):
    """Perimeter walls of the standing west part between heights z0 and z1."""
    g = GAP
    if "W" in which:
        box("wall", (-2 - T, -1.5 - T, z0), (-2 + T, 1.5 + T, z1), rgba, True, note="west")
    if "N" in which:
        box("wall", (-2 + T + g, 1.5 - T, z0), (x_east - T - g, 1.5 + T, z1), rgba, True, note="north")
    if "S" in which:
        box("wall", (-2 + T + g, -1.5 - T, z0), (x_east - T - g, -1.5 + T, z1), rgba, True, note="south")
    if "E" in which:
        box("wall", (x_east - T, -1.5 - T, z0), (x_east + T, 1.5 + T, z1), rgba, True, note="east face of the standing part")


def build():
    g = GAP
    # ---- ground storey -----------------------------------------------------------------------
    z0, z1 = 0.0, H
    box("wall", (-2 - T, -1.5 - T, z0), (-2 + T, 1.5 + T, z1), WALL, True, note="west")
    box("wall", (-2 + T + g, 1.5 - T, z0), (2 - T - g, 1.5 + T, z1), WALL, True, note="north")
    box("wall", (2 - T, -1.5 - T, z0), (2 + T, 1.5 + T, z1), WALL, True, note="east")
    box("wall", (-2 + T + g, -1.5 - T, z0), (-0.6, -1.5 + T, z1), WALL, True, note="south, west of the entrance")
    box("wall", (0.0, -1.5 - T, z0), (1.2, -1.5 + T, z1), WALL, True, note="south, between entrance and breach")
    box("wall", (1.7, -1.5 - T, z0), (2 - T - g, -1.5 + T, z1), WALL, True, note="south, east of the breach")
    # interior wall x=0.4 with a door at y 0.5..1.1
    box("wall", (0.4 - T, -1.5 + T + g, z0), (0.4 + T, 0.5, z1), WALL2, True, note="interior, south of the door")
    box("wall", (0.4 - T, 1.1, z0), (0.4 + T, 1.5 - T - g, z1), WALL2, True, note="interior, north of the door")

    # ---- standing west part: F1 (with the broken ledge), storey 2, F2, storey 3 --------------
    f1 = H + 0.002
    box("slab", (-2 - T, -1.5 - T, f1), (0.9, 1.5 + T, f1 + 2 * T), SLAB, True,
        note="floor 1; juts to x=0.9 over the east room (broken ledge)")
    s2 = f1 + 2 * T + 0.002
    storey_walls(s2, s2 + H, WALL)
    f2 = s2 + H + 0.002
    box("slab", (-2 - T, -1.5 - T, f2), (0.4 + T, 1.5 + T, f2 + 2 * T), SLAB, True, note="floor 2")
    s3 = f2 + 2 * T + 0.002
    storey_walls(s3, s3 + 0.8, WALL2, which=("W", "N"))

    # ---- east room: the lean-to void (c2) -----------------------------------------------------
    # Slab from the floor at x=0.9 up to the east wall top region at x=1.95, z=0.9; wedged (braced).
    add("slab", (1.425, 0.9, 0.45 + 0.03), (0.66, 0.5, 0.03), SLAB, True, euler="0 -40.6 0",
        note="lean-to slab over c2, wedged against the east wall")
    box("rubble", (0.9, 0.27, 0.0), (1.6, 0.39, 0.3), RUBBLE, True, density=600,
        note="lean-to closure, heavy")
    box("rubble", (1.6 + g, 0.27, 0.0), (1.9, 0.39, 0.25), LIGHT, False, mass=1.2,
        note="lean-to closure, light (G2): the Responder can clear it")

    # ---- east room: the pancake void (c3) -----------------------------------------------------
    for x, y in ((0.7, -1.2), (1.4, -1.2), (1.05, -0.5)):
        box("rubble", (x - 0.08, y - 0.08, 0.0), (x + 0.08, y + 0.08, 0.3), RUBBLE, True, density=600,
            note="pier under the pancake slab")
    box("slab", (0.6, -1.3, 0.302), (1.5, -0.4, 0.402), SLAB, True, note="pancake slab over c3, on three piers")

    # ---- breach rubble (c4 behind it) ---------------------------------------------------------
    box("rubble", (1.3, -1.6, 0.0), (1.46, -1.36, 0.16), LIGHT, False, mass=1.5,
        note="light block in the breach (G1): the Responder can clear it")
    box("rubble", (1.75, -2.1, 0.0), (2.35, -1.9, 0.08), RUBBLE, False, density=600,
        note="fallen south-wall section lying outside, east of the breach")

    # ---- loose slabs the aftershock drops -----------------------------------------------------
    # LS_a: leaning on the east wall's inner face (x=1.95), foot on the floor, at 60 degrees.
    add("rubble", (1.95 - 0.226, -0.15, 0.3614), (0.4, 0.15, 0.03), RUBBLE, False, euler="0 -60 0", density=600,
        friction=LOOSE_FRICTION, note="LS_a: loose slab leaning on the east wall")
    # LS_b: standing on the F1 ledge (top z = f1 + 0.1), leaning on the storey-2 east face (x=0.45).
    ledge = f1 + 2 * T
    add("rubble", (0.45 + 0.201, -0.6, ledge + 0.318), (0.35, 0.25, 0.03), RUBBLE, False, euler="0 60 0",
        density=600, friction=LOOSE_FRICTION, note="LS_b: loose slab on the F1 ledge, leaning on the storey-2 east wall")


CASUALTIES = [
    # name, pos, euler, voice (0 silent .. 1 loud), note
    ("c1", (-1.3, 0.8, 0.12), "0 90 0", 0.0, "west room, in the open, unconscious (silent): camera and thermal"),
    ("c2", (1.65, 0.9, 0.12), "90 0 0", 1.0, "in the lean-to void, enclosed: sound only until G2 is cleared"),
    ("c3", (1.05, -0.9, 0.11), "0 90 0", 0.4, "under the pancake slab: thermal from low down, faint sound"),
    ("c4", (1.75, -1.05, 0.12), "90 0 0", 0.7, "south-east corner behind the breach rubble: sound, thermal close up"),
]


def casualty_xml():
    out = []
    for name, (x, y, z), euler, _voice, note in CASUALTIES:
        r = 0.1 if name == "c3" else 0.12
        out.append(f'    <!-- {name}: {note} -->\n'
                   f'    <body name="casualty_{name}" pos="{x} {y} {z}" euler="{euler}">\n'
                   f'      <geom name="{name}_g" type="capsule" size="{r} 0.2" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>\n'
                   f'    </body>')
    return "\n".join(out)


def xml():
    build()
    bodies = "\n".join(b[2] for b in blocks)
    braces = "\n".join(f'    <weld name="brace_{n}" body1="{n}" body2="plate"/>' for n, _, _, br in blocks if br)
    light = [n for n, label, x, br in blocks if not br and 'mass="' in x and float(x.split('mass="')[1].split('"')[0]) < 2]
    grips = "\n".join(f'    <weld name="grip_{n}" body1="responder" body2="{n}" active="false"/>' for n in light)
    voices = "\n".join(f'    <numeric name="voice_{n}" data="{v}"/>' for n, _p, _e, v, _note in CASUALTIES)
    return f"""<!--
  AFTERSHOCK collapsed tower scene (ref Y1). GENERATED by sim/scenes/make_tower.py: edit that, not this.
  Run with SIM_SCENE=tower. See the generator's docstring for the plan, the voids and the casualties.
  Ground (mocap) + welded plate, robots, supplies and the spare block follow the backup scene's conventions.
-->
<mujoco model="aftershock_tower">
  <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="3" cone="elliptic" impratio="10"/>

  <visual>
    <global offwidth="1280" offheight="960"/>
  </visual>

  <default>
    <geom friction="1 0.005 0.0001"/>
  </default>

  <custom>
    <!-- How loud each casualty is (0 silent .. 1 calling out), read by sim/world.py for the acoustic sensor. -->
{voices}
  </custom>

  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.35 0.4 0.45" rgb2="0.05 0.05 0.08" width="256" height="256"/>
  </asset>

  <worldbody>
    <light name="sun" pos="0 0 8" dir="0 0 -1" directional="true" diffuse="0.8 0.8 0.8"/>

    <body name="ground" mocap="true" pos="0 0 0"/>
    <body name="plate" pos="0 0 0" gravcomp="1">
      <freejoint/>
      <geom name="floor" type="box" size="4.5 4.5 0.05" pos="0 0 -0.05" density="100" rgba="0.5 0.5 0.5 1"/>
    </body>

{bodies}

{casualty_xml()}

    <body name="x1" pos="0 0 -1" gravcomp="1">
      <freejoint/>
      <geom name="x1_rubble" type="box" size="0.1 0.1 0.08" density="600" contype="0" conaffinity="0" rgba="0.65 0.4 0.3 1"/>
    </body>

    <!-- Scout: starts outside the entrance (x -0.6..0) facing +y. -->
    <body name="scout" mocap="true" pos="-0.3 -2.3 0.075" quat="0.7071068 0 0 0.7071068">
      <geom name="scout_chassis" type="box" size="0.1 0.08 0.04" pos="0 0 -0.035" contype="0" conaffinity="0" rgba="0.2 0.5 0.9 1"/>
      <geom name="scout_mast" type="cylinder" size="0.02 0.02" pos="0 0 0.02" contype="0" conaffinity="0" rgba="0.1 0.1 0.1 1"/>
      <camera name="scout_cam" pos="0.1 0 0.03" xyaxes="0 -1 0 0 0 1" fovy="60"/>
    </body>

    <!-- Responder: behind the Scout, facing +y; robot geoms are group 3. -->
    <body name="responder" mocap="true" pos="-0.3 -2.9 0.05" quat="0.7071068 0 0 0.7071068">
      <geom name="responder_chassis" type="box" size="0.16 0.07 0.05" group="3" contype="0" conaffinity="0" rgba="0.95 0.6 0.1 1"/>
      <geom name="responder_gripper" type="box" size="0.02 0.06 0.015" pos="0.17 0 0.03" group="3" contype="0" conaffinity="0" rgba="0.15 0.15 0.15 1"/>
    </body>
    <body name="water" pos="-0.3 -3.0 0.16"><freejoint/><geom name="water_supply" type="cylinder" size="0.035 0.06" mass="0.5" group="3" rgba="0.2 0.55 1 1"/></body>
    <body name="first_aid_kit" pos="-0.3 -2.9 0.13"><freejoint/><geom name="first_aid_kit_supply" type="box" size="0.05 0.035 0.03" mass="0.4" group="3" rgba="0.9 0.15 0.15 1"/></body>
    <body name="radio" pos="-0.3 -2.8 0.145"><freejoint/><geom name="radio_supply" type="box" size="0.025 0.02 0.045" mass="0.3" group="3" rgba="0.15 0.15 0.15 1"/></body>

    <camera name="overview" pos="0 -6.5 5.5" xyaxes="1 0 0 0 0.65 0.76"/>
  </worldbody>

  <equality>
    <weld name="plate_to_ground" body1="plate" body2="ground" solref="0.004 1"/>
{braces}
    <weld name="carry_water" body1="responder" body2="water" active="true"/>
    <weld name="carry_first_aid_kit" body1="responder" body2="first_aid_kit" active="true"/>
    <weld name="carry_radio" body1="responder" body2="radio" active="true"/>
{grips}
  </equality>
</mujoco>
"""


def main():
    text = xml()
    OUT.write_text(text, encoding="utf-8", newline="\n")
    for name, label, x, braced in blocks:
        note = x.split("<!-- ")[1].split(" -->")[0] if "<!--" in x else ""
        print(f"{name:4} {label:6} {'braced' if braced else 'free  '} {note}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
