"""Generate tabletop collapse photos for sim/photos/set1 and sim/photos/set2."""

import pathlib

import mujoco
from PIL import Image

from sim.scene_builder import make_renderer


def generate():
    p1 = pathlib.Path("sim/photos/set1")
    p2 = pathlib.Path("sim/photos/set2")
    p1.mkdir(parents=True, exist_ok=True)
    p2.mkdir(parents=True, exist_ok=True)
    pathlib.Path("sim/generated").mkdir(parents=True, exist_ok=True)

    # Base model
    m = mujoco.MjModel.from_xml_path("sim/scenes/backup.xml")
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    renderer = make_renderer(m, height=480, width=640)
    if renderer is None:
        return

    # Set 1: 4 photos from distinct angles
    renderer.update_scene(d, camera="overview")
    Image.fromarray(renderer.render()).save(p1 / "photo1.jpg", format="JPEG", quality=90)

    renderer.update_scene(d, camera="scout_cam")
    Image.fromarray(renderer.render()).save(p1 / "photo2.jpg", format="JPEG", quality=90)

    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat = [0.5, 0.25, 0.5]
    cam.distance = 4.5
    cam.elevation = -30
    cam.azimuth = 45
    renderer.update_scene(d, camera=cam)
    Image.fromarray(renderer.render()).save(p1 / "photo3.jpg", format="JPEG", quality=90)

    cam.distance = 5.0
    cam.elevation = -85
    cam.azimuth = 0
    renderer.update_scene(d, camera=cam)
    Image.fromarray(renderer.render()).save(p1 / "photo4.jpg", format="JPEG", quality=90)

    # Set 2: tabletop variation with alternate rubble/casualty configuration
    xml_text = pathlib.Path("sim/scenes/backup.xml").read_text(encoding="utf-8")
    xml2 = xml_text.replace(
        'body name="b11" pos="1.25 0.45 0.08"',
        'body name="b11" pos="0.2 0.2 0.08"'
    ).replace(
        'body name="casualty_c1" pos="2.0 1.0 0.12"',
        'body name="casualty_c1" pos="1.8 0.5 0.12"'
    )
    m2 = mujoco.MjModel.from_xml_string(xml2)
    d2 = mujoco.MjData(m2)
    mujoco.mj_forward(m2, d2)
    renderer2 = make_renderer(m2, height=480, width=640)
    if renderer2 is None:
        return

    cam.distance = 4.8
    cam.elevation = -35
    cam.azimuth = 135
    cam.lookat = [0.5, 0.25, 0.5]
    renderer2.update_scene(d2, camera=cam)
    Image.fromarray(renderer2.render()).save(p2 / "photo1.jpg", format="JPEG", quality=90)

    cam.distance = 3.2
    cam.elevation = -22
    cam.azimuth = 80
    cam.lookat = [0.5, 0.0, 0.3]
    renderer2.update_scene(d2, camera=cam)
    Image.fromarray(renderer2.render()).save(p2 / "photo2.jpg", format="JPEG", quality=90)

    cam.distance = 2.6
    cam.elevation = -28
    cam.azimuth = -45
    cam.lookat = [1.8, 0.5, 0.2]
    renderer2.update_scene(d2, camera=cam)
    Image.fromarray(renderer2.render()).save(p2 / "photo3.jpg", format="JPEG", quality=90)

    cam.distance = 5.0
    cam.elevation = -80
    cam.azimuth = 90
    cam.lookat = [0.5, 0.25, 0.5]
    renderer2.update_scene(d2, camera=cam)
    Image.fromarray(renderer2.render()).save(p2 / "photo4.jpg", format="JPEG", quality=90)

    print("Generated 4 photos in set1 and 4 photos in set2.")

if __name__ == "__main__":
    generate()
