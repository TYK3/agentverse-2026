"""Write sim/scenes/levels.xml, the L4 multi-level scene. Run: python sim/scenes/make_levels.py

Geometry is computed here, not typed into the XML, so each ramp's top face meets the slabs exactly.
"""

import math
import pathlib

T = 0.06          # slab and ramp thickness
H = 0.6           # level height: B3 at -3H, B2 at -2H, B1 at -H, ground at 0, L1 at +H
W = 0.04          # wall half thickness
X0, X1, Y0, Y1 = 0.0, 5.0, 0.0, 2.4
FLOOR = "0.5 0.5 0.5 1"
WALL = "0.8 0.7 0.5 1"
RUBBLE = "0.55 0.5 0.45 1"
OUT = pathlib.Path(__file__).with_name("levels.xml")


def box(name, lo, hi, rgba=WALL):
    c = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    s = [(b - a) / 2 for a, b in zip(lo, hi, strict=True)]
    return (f'    <geom name="{name}" type="box" pos="{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}" '
            f'size="{s[0]:.4f} {s[1]:.4f} {s[2]:.4f}" rgba="{rgba}"/>')


def ramp(name, xa, za, xb, zb, y0, y1, rgba="0.45 0.55 0.6 1"):
    """A plank whose top face runs from (xa, za) to (xb, zb), across y0..y1."""
    if xb < xa:
        xa, za, xb, zb = xb, zb, xa, za
    dx, dz = xb - xa, zb - za
    length = math.hypot(dx, dz)
    th = math.atan2(dz, dx)                       # slope angle; dx > 0 so the normal points up
    nx, nz = -math.sin(th), math.cos(th)
    cx, cz = (xa + xb) / 2 - nx * T / 2, (za + zb) / 2 - nz * T / 2
    return (f'    <geom name="{name}" type="box" pos="{cx:.4f} {(y0 + y1) / 2:.4f} {cz:.4f}" '
            f'size="{length / 2 + 0.01:.4f} {(y1 - y0) / 2:.4f} {T / 2:.4f}" '
            f'euler="0 {-math.degrees(th):.4f} 0" rgba="{rgba}"/>')


def geoms():
    top = 2 * H + 0.2
    return [
        # B3 floor and the outer walls, which run from B3 up past L1
        box("b3_floor", [X0, Y0, -3 * H - T], [X1, Y1, -3 * H], FLOOR),
        box("wall_s", [X0 - W, Y0 - 2 * W, -3 * H], [X1 + W, Y0, top]),
        box("wall_n", [X0 - W, Y1, -3 * H], [X1 + W, Y1 + 2 * W, top]),
        box("wall_w", [X0 - 2 * W, Y0, -3 * H], [X0, Y1, top]),
        box("wall_e", [X1, Y0, -3 * H], [X1 + 2 * W, Y1, top]),
        # B2 floor, with the shaft x 1.5..4.5, y 0..0.6 left open for ramp R4 (B2 -> B3, heading west).
        # R4 lands on B3 at x = 2.5; the 1 m past it is the shaft foot, where the Scout turns north
        # under r4_end_rail (a 0.2 m rail at B2, 0.54 m clear above B3) into the rest of B3.
        box("b2_floor_w", [X0, Y0, -2 * H - T], [1.5, Y1, -2 * H], FLOOR),
        box("b2_floor_m", [1.5, 0.6, -2 * H - T], [4.5, Y1, -2 * H], FLOOR),
        box("b2_floor_e", [4.5, Y0, -2 * H - T], [X1, Y1, -2 * H], FLOOR),
        ramp("ramp_r4", 4.5, -2 * H, 2.5, -3 * H, Y0, 0.6),
        box("r4_side", [2.5, 0.6, -3 * H], [4.5, 0.6 + 2 * W, -2 * H + 0.2]),  # wall under R4, rail above B2
        box("r4_end_rail", [1.5, 0.6, -2 * H - T], [2.5, 0.6 + 2 * W, -2 * H + 0.2]),
        box("r4_west_rail", [1.5 - 2 * W, Y0, -2 * H - T], [1.5, 0.6 + 2 * W, -2 * H + 0.2]),
        box("r4_back", [4.5, Y0, -3 * H], [4.5 + 2 * W, 0.6, -2 * H - T]),     # closes the space under R4
        # B1 floor, with the shaft x 2.5..5, y 1.8..2.4 left open for ramp R3 (B1 -> B2, heading east).
        # R3 lands on B2 at x = 4.5; the 0.5 m past it is the shaft foot, where the Scout turns south
        # under r3_end_rail (a 0.2 m rail at B1, 0.54 m clear above B2) into the rest of B2.
        box("b1_floor_s", [X0, Y0, -H - T], [X1, 1.8, -H], FLOOR),
        box("b1_floor_nw", [X0, 1.8, -H - T], [2.5, Y1, -H], FLOOR),
        ramp("ramp_r3", 2.5, -H, 4.5, -2 * H, 1.8, Y1),
        box("r3_side", [2.5, 1.8 - 2 * W, -2 * H], [4.5, 1.8, -H + 0.2]),   # wall under R3, rail above B1
        box("r3_end_rail", [4.5, 1.8 - 2 * W, -H - T], [X1, 1.8, -H + 0.2]),
        box("r3_back", [2.5 - 2 * W, 1.8, -2 * H], [2.5, Y1, -H - T]),     # closes the space under R3
        # Ground floor, with the shaft x 1.5..3.5, y 0..0.6 left open for ramp R1 (ground -> B1)
        box("g_floor_w", [X0, Y0, -T], [1.5, Y1, 0], FLOOR),
        box("g_floor_m", [1.5, 0.6, -T], [3.5, Y1, 0], FLOOR),
        box("g_floor_e", [3.5, Y0, -T], [X1, Y1, 0], FLOOR),
        ramp("ramp_r1", 3.5, 0.0, 1.5, -H, Y0, 0.6),
        box("r1_side", [1.5, 0.6, -H], [3.5, 0.6 + 2 * W, 0.2]),         # shaft wall; a 0.2 m rail above ground
        box("r1_end_rail", [1.5 - 2 * W, Y0, 0.0], [1.5, 0.6 + 2 * W, 0.2]),
        # L1 mezzanine over x 0..1.5; ramp R2 (L1 -> ground) over y 1.8..2.4, x 1.5 -> 3.5
        box("l1_floor", [X0, Y0, H - T], [1.5, Y1, H], FLOOR),
        box("l1_edge_rail", [1.5, Y0, H], [1.5 + 2 * W, 1.8 - 2 * W, H + 0.2]),
        ramp("ramp_r2", 1.5, H, 3.5, 0.0, 1.8, Y1),
        box("r2_side", [1.5, 1.8 - 2 * W, 0.0], [3.5, 1.8, H + 0.2]),     # wall under the ramp, rail above it
        box("r2_back", [1.5, 1.8, 0.0], [1.5 + 2 * W, Y1, H - T]),         # closes the space under the ramp
        # Rubble, so the levels differ
        box("b20_rubble", [4.2, 1.0, 0.0], [4.6, 1.3, 0.15], RUBBLE),
        box("b21_rubble", [0.9, 0.9, -H], [1.2, 1.2, -H + 0.12], RUBBLE),
        box("b22_rubble", [2.0, 0.9, -2 * H], [2.3, 1.2, -2 * H + 0.12], RUBBLE),
        box("b23_rubble", [3.5, 1.2, -3 * H], [3.8, 1.5, -3 * H + 0.12], RUBBLE),
    ]


HEADER = """<!--
  L4 multi-level scene, written by sim/scenes/make_levels.py (edit that, not this file).
  A mezzanine L1 (floor z = +0.6), the ground floor (z = 0) and basements B1 (z = -0.6), B2 (z = -1.2), B3 (z = -1.8).

  Plan view (x right, y up), footprint 5 m x 2.4 m:
     y=2.4 +-------------------------------------------+
           | L1 (x<1.5) |== ramp R2: L1 -> ground ==> |   y 1.8..2.4, x 1.5 -> 3.5, side wall at y = 1.8
     y=1.8 | edge rail  |                             |
           |            |   ground floor              |
     y=0.6 |            | <== ramp R1: ground -> B1 ==|   y 0..0.6, x 3.5 -> 1.5, railed shaft
     y=0   +-------------------------------------------+
         x=0         x=1.5                  x=3.5    x=5
  B1 lies under the whole footprint; R1 lands on it at x = 1.5. Casualty c1 lies in B1 at the west end.

  B1 plan view: ramp R3 (B1 -> B2) runs east over y 1.8..2.4, x 2.5 -> 4.5, in a railed shaft that is open
  down to B2 for x 2.5..5. B2 lies under the whole footprint; the Scout leaves R3's foot (x 4.5..5) south,
  under the rail at y = 1.8, which is 0.54 m above B2. Casualty c2 lies in B2 at the west end.

  B2 plan view: ramp R4 (B2 -> B3) runs west over y 0..0.6, x 4.5 -> 2.5, in a railed shaft that is open
  down to B3 for x 1.5..4.5. B3 lies under the whole footprint; the Scout leaves R4's foot (x 1.5..2.5)
  north, under the rail at y = 0.6, which is 0.54 m above B3. Casualty c3 lies in B3 at the west end.
  Every drop is railed (0.2 m) except the ramp mouths, because a 2D LiDAR cannot see a drop.
  Levels are static geoms, not b<number> blocks, so the aftershock check has nothing to shake here.
-->"""


def xml():
    body = "\n".join(geoms())
    return f"""{HEADER}
<mujoco model="aftershock_levels">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <visual><global offwidth="1280" offheight="960"/></visual>
  <default><geom friction="1 0.005 0.0001"/></default>
  <worldbody>
    <light name="sun" pos="2.5 1.2 6" dir="0 0 -1" directional="true" diffuse="0.8 0.8 0.8"/>
    <body name="ground" mocap="true" pos="0 0 0"/>
{body}
    <!-- Casualty c1 in B1: a fixed visual marker, no collisions. -->
    <body name="casualty_c1" pos="0.45 1.9 {-H + 0.12:.2f}" euler="0 90 0">
      <geom name="c1_g" type="capsule" size="0.1 0.25" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>
    </body>
    <!-- Casualty c2 in B2: a fixed visual marker, no collisions. -->
    <body name="casualty_c2" pos="0.45 0.4 {-2 * H + 0.12:.2f}" euler="0 90 0">
      <geom name="c2_g" type="capsule" size="0.1 0.25" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>
    </body>
    <!-- Casualty c3 in B3: a fixed visual marker, no collisions. -->
    <body name="casualty_c3" pos="0.45 2.0 {-3 * H + 0.12:.2f}" euler="0 90 0">
      <geom name="c3_g" type="capsule" size="0.1 0.25" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>
    </body>
    <!-- Scout as in backup.xml: mocap, origin = sensor origin 0.075 m above the floor, robot geoms in
         group 3. It starts on L1; sim/levels.py sets its height from the floor under it. -->
    <body name="scout" mocap="true" pos="0.5 0.5 {H + 0.075:.3f}">
      <geom name="scout_chassis" type="box" size="0.1 0.08 0.04" pos="0 0 -0.035" group="3" contype="0" conaffinity="0" rgba="0.2 0.5 0.9 1"/>
      <geom name="scout_mast" type="cylinder" size="0.02 0.02" pos="0 0 0.02" group="3" contype="0" conaffinity="0" rgba="0.1 0.1 0.1 1"/>
      <camera name="scout_cam" pos="0.1 0 0.03" xyaxes="0 -1 0 0 0 1" fovy="60"/>
    </body>
    <camera name="overview" pos="2.5 -3.5 3.2" xyaxes="1 0 0 0 0.6 0.8"/>
  </worldbody>
</mujoco>
"""


if __name__ == "__main__":
    OUT.write_text(xml(), encoding="utf-8")
    print(f"wrote {OUT}")
