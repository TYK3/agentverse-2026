"""Download the free demo assets (ref A1) into sim/assets/cache/ (gitignored).

    python3 sim/assets/fetch.py

Every source is pinned here with its licence; sim/assets/build_glb.py bakes them into one GLB and
console/public/models/CREDITS.json lists them for the console credits card. No account, key or token is
needed for any of them. Files already in the cache are not downloaded again.
"""

import pathlib
import sys
import urllib.request

CACHE = pathlib.Path(__file__).parent / "cache"
UA = "aftershock-asset-fetch/0.1"
PH = "https://dl.polyhaven.org/file/ph-assets"
MENAGERIE = "https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/main/unitree_go1"

CREDITS = [
    {
        "asset": "Rebar Reinforced Concrete (texture)",
        "author": "Amal Kumar",
        "source": "https://polyhaven.com/a/rebar_reinforced_concrete",
        "licence": "CC0",
        "used_for": "walls, slabs and rubble",
    },
    {
        "asset": "Parking Garage (HDRI)",
        "author": "Poly Haven",
        "source": "https://polyhaven.com/a/parking_garage",
        "licence": "CC0",
        "used_for": "console lighting and reflections",
    },
    {
        "asset": "Rover",
        "author": "Quaternius",
        "source": "https://poly.pizza/m/tzOLXetacM",
        "licence": "CC0",
        "used_for": "Responder body (scaled to its 0.508 x 0.43 m footprint)",
    },
    {
        "asset": "First Aid Kit",
        "author": "Quaternius",
        "source": "https://poly.pizza/m/Hp80p6148W",
        "licence": "CC0",
        "used_for": "first_aid_kit supply",
    },
    {
        "asset": "Unitree Go1 (MuJoCo Menagerie)",
        "author": "Unitree Robotics, Google DeepMind",
        "source": "https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_go1",
        "licence": "BSD-3-Clause",
        "used_for": "Scout body (scaled to its 0.322 m length)",
    },
]

FILES = {
    "concrete_diff_1k.jpg": f"{PH}/Textures/jpg/1k/rebar_reinforced_concrete/rebar_reinforced_concrete_diff_1k.jpg",
    "concrete_nor_gl_1k.jpg": f"{PH}/Textures/jpg/1k/rebar_reinforced_concrete/rebar_reinforced_concrete_nor_gl_1k.jpg",
    "concrete_rough_1k.jpg": f"{PH}/Textures/jpg/1k/rebar_reinforced_concrete/rebar_reinforced_concrete_rough_1k.jpg",
    "parking_garage_1k.hdr": f"{PH}/HDRIs/hdr/1k/parking_garage_1k.hdr",
    "rover.glb": "https://static.poly.pizza/7992e6b4-8add-45a9-86fd-f208237d293c.glb",
    "first_aid_kit.glb": "https://static.poly.pizza/41249676-0965-40df-8dd7-eee79dd9e6cf.glb",
    "go1/go1.xml": f"{MENAGERIE}/go1.xml",
    "go1/LICENSE": f"{MENAGERIE}/LICENSE",
    **{f"go1/assets/{n}.stl": f"{MENAGERIE}/assets/{n}.stl" for n in ("trunk", "hip", "thigh", "thigh_mirror", "calf")},
}


def fetch(name: str, url: str) -> pathlib.Path:
    out = CACHE / name
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    out.write_bytes(data)
    print(f"{name}: {len(data) / 1e6:.2f} MB")
    return out


def main() -> int:
    for name, url in FILES.items():
        fetch(name, url)
    print(f"assets in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
