"""The tower's basements and stair/lift core (ref A1): one list of boxes, used by both the console GLB
(sim/assets/build_glb.py) and the MuJoCo collision scene this script writes.

    python3 sim/assets/annex.py          # writes sim/scenes/tower_annex.xml
    SIM_SCENE=sim/scenes/tower_annex.xml ...

Frame: the tower scene's (metres, z up). The tower's footprint is x -2..2, y -1.5..1.5, storeys 1 m.
  - B1..B3: three basement levels under the footprint, slab tops at z -1, -2, -3, perimeter walls on
    the west, north and south, two rows of columns. The east side is open onto an excavation pit
    (x 2.05..3.2) so a camera from the south-east sees the levels in section.
  - Core: a stairwell (south half) and a lift shaft (north half) on the west side, x -2.95..-2.05,
    from B3 (z -3) to the top storey (z 3). Switchback stairs, one landing per half storey; the lift car
    is stopped at B2.

Nothing here enters the robots' ground storey (x -2..2, y -1.5..1.5, z 0..3) or the area they drive on
around it (z >= 0 outside the core): everything is below the floor plate or inside the core walls,
which stand west of the tower's west wall. In MuJoCo the boxes are massless geoms of a jointless
"annex" body inside the floor plate body: rigidly part of the plate, so they shake with the ground in
an aftershock and never touch it, and, in the "braced" class, never touch the welded structure; robots
and loose rubble still hit them. They are not geoms of the plate body itself: MuJoCo's midphase then
builds a bounding volume tree for the plate and drops the exactly-touching rubble-on-floor contacts,
which changes the scene. The plate still covers the pit and the core at z 0, so the robots' world is
unchanged.
"""

import pathlib
import re

H = 1.0
T = 0.05
STOREYS = range(-3, 3)          # storey base heights the stairs climb from (B3 .. storey 3)
TOWER = pathlib.Path(__file__).resolve().parents[1] / "scenes" / "tower.xml"
OUT = TOWER.with_name("tower_annex.xml")

# (name, label, lo corner, hi corner)
Box = tuple[str, str, tuple[float, float, float], tuple[float, float, float]]


def boxes() -> list[Box]:
    out: list[Box] = []

    def box(name, label, lo, hi):
        out.append((name, label, tuple(round(v, 4) for v in lo), tuple(round(v, 4) for v in hi)))

    # Basement slabs: B1 and B2 under the footprint, B3 also under the core and the pit.
    box("B1_slab", "slab", (-2.05, -1.55, -1 - 2 * T), (2.05, 1.55, -1))
    box("B2_slab", "slab", (-2.05, -1.55, -2 - 2 * T), (2.05, 1.55, -2))
    box("B3_slab", "slab", (-2.95, -1.65, -3 - 2 * T), (3.3, 1.65, -3))
    # Basement perimeter (east side open onto the pit) and the pit's retaining walls.
    box("B_wall_w", "wall", (-2.05, -1.55, -3), (-1.95, 1.55, -2 * T))
    box("B_wall_n", "wall", (-1.95, 1.45, -3), (2.05, 1.55, -2 * T))
    box("B_wall_s", "wall", (-1.95, -1.55, -3), (2.05, -1.45, -2 * T))
    box("pit_wall_e", "wall", (3.2, -1.65, -3), (3.3, 1.65, -2 * T))
    box("pit_wall_n", "wall", (2.05, 1.55, -3), (3.2, 1.65, -2 * T))
    box("pit_wall_s", "wall", (2.05, -1.65, -3), (3.2, -1.55, -2 * T))
    # Columns, two rows of three per level.
    for k in (1, 2, 3):
        top = -(k - 1) - 2 * T          # underside of the slab (or the floor plate) above
        for x in (-1.0, 0.0, 1.0):
            for y in (-0.5, 0.5):
                box(f"B{k}_col_{x:+.0f}_{y:+.1f}", "wall", (x - 0.06, y - 0.06, -k), (x + 0.06, y + 0.06, top))

    # Core walls (its east side is the tower's west wall above ground and the basement wall below).
    box("core_wall_w", "wall", (-2.95, -1.55, -3), (-2.85, 1.55, 3.0))
    box("core_wall_n", "wall", (-2.85, 1.45, -3), (-2.05, 1.55, 3.0))
    box("core_wall_s", "wall", (-2.85, -1.55, -3), (-2.05, -1.45, 2.3))      # broken off at 2.3 m
    box("core_divider", "wall", (-2.85, -0.05, -3), (-2.05, 0.05, 3.0))

    # Switchback stairs in the south half: flight A climbs north on the west side, a mid landing, flight
    # B climbs back south on the east side to the next floor landing. 5 risers of 0.1 m per flight.
    tread = 0.16
    for z0 in STOREYS:
        s = f"{z0:+d}"
        for i in range(5):
            y = -1.15 + i * tread
            top = z0 + (i + 1) * 0.1
            box(f"stair{s}_a{i}", "stair", (-2.85, y, top - 0.06), (-2.47, y + tread, top))
        box(f"stair{s}_mid", "stair", (-2.85, -0.35, z0 + 0.5 - 0.08), (-2.05, -0.05, z0 + 0.5))
        for i in range(5):
            y = -0.35 - (i + 1) * tread
            top = z0 + 0.5 + (i + 1) * 0.1
            box(f"stair{s}_b{i}", "stair", (-2.43, y, top - 0.06), (-2.05, y + tread, top))
        if z0 + H < 3:
            box(f"stair{s}_landing", "stair", (-2.85, -1.45, z0 + H - 0.08), (-2.05, -1.15, z0 + H))

    # Lift shaft in the north half: guide rails, the car stopped at B2, its cable.
    box("lift_rail_w", "lift", (-2.84, 0.7, -3), (-2.82, 0.8, 3.0))
    box("lift_rail_e", "lift", (-2.08, 0.7, -3), (-2.06, 0.8, 3.0))
    box("lift_car", "lift", (-2.78, 0.15, -2.0), (-2.12, 1.35, -1.15))
    box("lift_cable", "lift", (-2.46, 0.74, -1.15), (-2.44, 0.76, 3.0))
    return out


def footprint_clear(b: Box) -> bool:
    """True when a box stays out of the robots' world: below the plate, or west of the tower's wall."""
    _, _, _lo, hi = b
    return hi[2] <= 0 or hi[0] <= -2.05


def mjcf_geoms() -> str:
    lines = []
    for name, label, lo, hi in boxes():
        c = " ".join(f"{(a + b) / 2:.4f}" for a, b in zip(lo, hi, strict=True))
        s = " ".join(f"{(b - a) / 2:.4f}" for a, b in zip(lo, hi, strict=True))
        lines.append(f'        <geom name="annex_{name}_{label}" type="box" pos="{c}" size="{s}" class="braced" '
                     f'density="0" rgba="0.6 0.6 0.62 1"/>')
    return "\n".join(lines)


def write_scene(src: pathlib.Path = TOWER, out: pathlib.Path = OUT) -> pathlib.Path:
    """tower.xml plus the annex boxes as geoms of the floor plate body, inserted after its floor geom."""
    xml = src.read_text()
    marker = re.search(r'<body name="plate".*?<geom name="floor"[^\n]*\n', xml, re.DOTALL)
    if not marker:
        raise ValueError(f"{src}: no plate body with a floor geom to attach the annex to")
    head = ("<!-- GENERATED by sim/assets/annex.py from tower.xml: the tower plus its basements and stair/lift\n"
            "     core (ref A1) as static collision boxes. Edit annex.py or make_tower.py, not this. -->\n")
    annex = ('      <!-- A1 annex: basements B1-B3, stairwell, lift shaft -->\n      <body name="annex">\n'
             + mjcf_geoms() + "\n      </body>\n")
    body = xml[:marker.end()] + annex + xml[marker.end():]
    out.write_text(head + body)
    return out


if __name__ == "__main__":
    print(write_scene())
