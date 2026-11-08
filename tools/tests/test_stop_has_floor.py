"""STOP-HAS-FLOOR: every stop in a real run log can be placed on its floor (ref b3).

A stop is a `pose` record whose state is not moving (idle, arrived, blocked, frozen). Its floor is the
last floor the Scout reached before it (the run's `level` records). Each stop must say where it is:
- a stop whose `level` is a floor name must name that floor, at that floor's height (FLOOR_Z plus the
  Scout's RIDE, within Z_TOL);
- a stop logged on a `ramp` names no floor itself, so it must be on one of the two ramps at its floor:
  strictly between its floor's height and the next floor's down (the way on), or the floor above's (the
  ramp it came down: the Scout sometimes backs part-way up it while exploring).

Finding: on real runs a stop on a ramp is common (the Scout reaches route waypoints part-way down a
ramp): 13 of 29 stops in the B2 run and 9 of 40 in the B3 run are logged as `ramp`, not as a floor. So
"every stop's own level field is a floor" does not hold on real logs; "every stop can be placed on its
floor" does, and is what this checks. Second finding: in the B3 run the Scout reached B2 at 142.9 s and
at 149.0 s stopped part-way back up the ramp it came down (z -1.117, above B2's -1.2); the `level`
records only log new floors, so this climb-back is visible only in the poses.

Real logs: REAL (seed 0 on main, both 9/9): every level record and every pose (t, pos, state, level) of a
B2 run and a B3 run; plus full runs/b2-*.jsonl and runs/b3-*.jsonl (or $B2_LOG / $B3_LOG) when present
(they skip otherwise; CI has none).
"""

import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}   # sim/levels.py LEVEL_Z
ORDER = ["L1", "ground", "B1", "B2", "B3"]
RIDE = 0.075
Z_TOL = 0.02
MOVING = "moving"

REAL = {
    'b2-0': [
        {'t': 0.0, 'kind': 'level', 'level': 'L1'},
        {'t': 0.0, 'kind': 'pose', 'pos': [0.5, 0.5, 0.675], 'state': 'idle', 'level': 'L1'},
        {'t': 1.0, 'kind': 'pose', 'pos': [0.507, 0.8, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 2.0, 'kind': 'pose', 'pos': [0.515, 1.1, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 3.0, 'kind': 'pose', 'pos': [0.522, 1.4, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 4.0, 'kind': 'pose', 'pos': [0.645, 1.525, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 5.0, 'kind': 'pose', 'pos': [0.852, 1.652, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 6.0, 'kind': 'pose', 'pos': [1.022, 1.822, 0.675], 'state': 'arrived', 'level': 'L1'},
        {'t': 7.0, 'kind': 'pose', 'pos': [1.23, 1.973, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 8.0, 'kind': 'pose', 'pos': [1.424, 2.025, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 9.0, 'kind': 'pose', 'pos': [1.647, 2.068, 0.631], 'state': 'moving', 'level': 'ramp'},
        {'t': 10.0, 'kind': 'pose', 'pos': [1.947, 2.071, 0.541], 'state': 'moving', 'level': 'ramp'},
        {'t': 11.0, 'kind': 'pose', 'pos': [2.247, 2.073, 0.451], 'state': 'moving', 'level': 'ramp'},
        {'t': 12.0, 'kind': 'pose', 'pos': [2.499, 2.032, 0.375], 'state': 'moving', 'level': 'ramp'},
        {'t': 13.0, 'kind': 'pose', 'pos': [2.669, 2.075, 0.324], 'state': 'arrived', 'level': 'ramp'},
        {'t': 14.0, 'kind': 'pose', 'pos': [2.775, 2.025, 0.293], 'state': 'arrived', 'level': 'ramp'},
        {'t': 15.0, 'kind': 'pose', 'pos': [2.796, 2.087, 0.286], 'state': 'moving', 'level': 'ramp'},
        {'t': 16.0, 'kind': 'pose', 'pos': [2.981, 2.069, 0.231], 'state': 'moving', 'level': 'ramp'},
        {'t': 17.0, 'kind': 'pose', 'pos': [3.081, 1.992, 0.201], 'state': 'moving', 'level': 'ramp'},
        {'t': 18.0, 'kind': 'pose', 'pos': [3.057, 2.041, 0.208], 'state': 'moving', 'level': 'ramp'},
        {'t': 19.0, 'kind': 'pose', 'pos': [3.239, 2.111, 0.153], 'state': 'moving', 'level': 'ramp'},
        {'t': 20.0, 'kind': 'pose', 'pos': [3.387, 1.963, 0.109], 'state': 'blocked', 'level': 'ramp'},
        {'t': 21.0, 'kind': 'pose', 'pos': [3.337, 2.019, 0.124], 'state': 'moving', 'level': 'ramp'},
        {'t': 21.6, 'kind': 'level', 'level': 'ground'},
        {'t': 22.0, 'kind': 'pose', 'pos': [3.496, 2.154, 0.076], 'state': 'moving', 'level': 'ground'},
        {'t': 23.0, 'kind': 'pose', 'pos': [3.687, 2.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 24.0, 'kind': 'pose', 'pos': [3.676, 2.091, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 25.0, 'kind': 'pose', 'pos': [3.744, 1.912, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 26.0, 'kind': 'pose', 'pos': [3.725, 1.725, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 27.0, 'kind': 'pose', 'pos': [3.654, 1.554, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 28.0, 'kind': 'pose', 'pos': [3.473, 1.482, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 29.0, 'kind': 'pose', 'pos': [3.173, 1.48, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 30.0, 'kind': 'pose', 'pos': [2.873, 1.478, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 31.0, 'kind': 'pose', 'pos': [2.573, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 32.0, 'kind': 'pose', 'pos': [2.303, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 33.0, 'kind': 'pose', 'pos': [2.003, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 34.0, 'kind': 'pose', 'pos': [1.703, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 35.0, 'kind': 'pose', 'pos': [1.475, 1.475, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 36.0, 'kind': 'pose', 'pos': [1.311, 1.311, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 37.0, 'kind': 'pose', 'pos': [1.12, 1.12, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 38.0, 'kind': 'pose', 'pos': [0.908, 0.908, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 39.0, 'kind': 'pose', 'pos': [0.696, 0.696, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 40.0, 'kind': 'pose', 'pos': [0.484, 0.484, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 41.0, 'kind': 'pose', 'pos': [0.481, 0.754, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 42.0, 'kind': 'pose', 'pos': [0.477, 1.054, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 43.0, 'kind': 'pose', 'pos': [0.625, 1.174, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 44.0, 'kind': 'pose', 'pos': [0.925, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 45.0, 'kind': 'pose', 'pos': [1.195, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 46.0, 'kind': 'pose', 'pos': [1.495, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 47.0, 'kind': 'pose', 'pos': [1.795, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 48.0, 'kind': 'pose', 'pos': [2.065, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 49.0, 'kind': 'pose', 'pos': [2.365, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 50.0, 'kind': 'pose', 'pos': [2.635, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 51.0, 'kind': 'pose', 'pos': [2.935, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 52.0, 'kind': 'pose', 'pos': [3.235, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 53.0, 'kind': 'pose', 'pos': [3.418, 1.031, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 54.0, 'kind': 'pose', 'pos': [3.625, 0.875, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 55.0, 'kind': 'pose', 'pos': [3.774, 0.697, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 56.0, 'kind': 'pose', 'pos': [3.726, 0.501, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 57.0, 'kind': 'pose', 'pos': [3.577, 0.327, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 58.0, 'kind': 'pose', 'pos': [3.277, 0.326, 0.008], 'state': 'moving', 'level': 'ramp'},
        {'t': 59.0, 'kind': 'pose', 'pos': [2.977, 0.326, -0.082], 'state': 'moving', 'level': 'ramp'},
        {'t': 60.0, 'kind': 'pose', 'pos': [2.677, 0.325, -0.172], 'state': 'moving', 'level': 'ramp'},
        {'t': 61.0, 'kind': 'pose', 'pos': [2.48, 0.431, -0.231], 'state': 'arrived', 'level': 'ramp'},
        {'t': 62.0, 'kind': 'pose', 'pos': [2.508, 0.368, -0.223], 'state': 'moving', 'level': 'ramp'},
        {'t': 63.0, 'kind': 'pose', 'pos': [2.768, 0.325, -0.145], 'state': 'moving', 'level': 'ramp'},
        {'t': 64.0, 'kind': 'pose', 'pos': [3.038, 0.325, -0.064], 'state': 'moving', 'level': 'ramp'},
        {'t': 65.0, 'kind': 'pose', 'pos': [3.305, 0.325, 0.017], 'state': 'moving', 'level': 'ramp'},
        {'t': 66.0, 'kind': 'pose', 'pos': [3.34, 0.24, 0.027], 'state': 'moving', 'level': 'ramp'},
        {'t': 67.0, 'kind': 'pose', 'pos': [3.383, 0.317, 0.04], 'state': 'moving', 'level': 'ramp'},
        {'t': 68.0, 'kind': 'pose', 'pos': [3.348, 0.409, 0.03], 'state': 'moving', 'level': 'ramp'},
        {'t': 69.0, 'kind': 'pose', 'pos': [3.165, 0.325, -0.025], 'state': 'moving', 'level': 'ramp'},
        {'t': 70.0, 'kind': 'pose', 'pos': [2.875, 0.325, -0.112], 'state': 'moving', 'level': 'ramp'},
        {'t': 71.0, 'kind': 'pose', 'pos': [2.635, 0.325, -0.184], 'state': 'moving', 'level': 'ramp'},
        {'t': 72.0, 'kind': 'pose', 'pos': [2.4, 0.242, -0.255], 'state': 'moving', 'level': 'ramp'},
        {'t': 73.0, 'kind': 'pose', 'pos': [2.227, 0.373, -0.307], 'state': 'arrived', 'level': 'ramp'},
        {'t': 74.0, 'kind': 'pose', 'pos': [2.013, 0.437, -0.371], 'state': 'blocked', 'level': 'ramp'},
        {'t': 75.0, 'kind': 'pose', 'pos': [2.145, 0.325, -0.331], 'state': 'moving', 'level': 'ramp'},
        {'t': 76.0, 'kind': 'pose', 'pos': [1.954, 0.346, -0.389], 'state': 'moving', 'level': 'ramp'},
        {'t': 77.0, 'kind': 'pose', 'pos': [1.875, 0.375, -0.412], 'state': 'arrived', 'level': 'ramp'},
        {'t': 78.0, 'kind': 'pose', 'pos': [1.944, 0.309, -0.392], 'state': 'moving', 'level': 'ramp'},
        {'t': 79.0, 'kind': 'pose', 'pos': [1.775, 0.225, -0.442], 'state': 'arrived', 'level': 'ramp'},
        {'t': 80.0, 'kind': 'pose', 'pos': [1.584, 0.416, -0.5], 'state': 'moving', 'level': 'ramp'},
        {'t': 80.1, 'kind': 'level', 'level': 'B1'},
        {'t': 81.0, 'kind': 'pose', 'pos': [1.533, 0.367, -0.515], 'state': 'moving', 'level': 'B1'},
        {'t': 82.0, 'kind': 'pose', 'pos': [1.363, 0.537, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 83.0, 'kind': 'pose', 'pos': [1.175, 0.536, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 84.0, 'kind': 'pose', 'pos': [0.935, 0.622, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 85.0, 'kind': 'pose', 'pos': [0.727, 0.773, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 86.0, 'kind': 'pose', 'pos': [0.633, 0.917, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 87.0, 'kind': 'pose', 'pos': [0.625, 1.217, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 88.0, 'kind': 'pose', 'pos': [0.668, 1.387, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 89.0, 'kind': 'pose', 'pos': [0.54, 1.557, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 90.0, 'kind': 'pose', 'pos': [0.545, 1.575, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 91.0, 'kind': 'pose', 'pos': [0.475, 1.575, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 92.0, 'kind': 'pose', 'pos': [0.745, 1.575, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 93.0, 'kind': 'pose', 'pos': [0.931, 1.681, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 94.0, 'kind': 'pose', 'pos': [1.02, 1.847, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 95.0, 'kind': 'pose', 'pos': [1.025, 2.075, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 96.0, 'kind': 'pose', 'pos': [1.195, 2.203, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 97.0, 'kind': 'pose', 'pos': [1.425, 2.125, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 98.0, 'kind': 'pose', 'pos': [1.725, 2.125, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 99.0, 'kind': 'pose', 'pos': [1.995, 2.125, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 100.0, 'kind': 'pose', 'pos': [2.295, 2.125, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 101.0, 'kind': 'pose', 'pos': [2.467, 1.983, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 102.0, 'kind': 'pose', 'pos': [2.291, 1.985, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 103.0, 'kind': 'pose', 'pos': [2.225, 1.745, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 104.0, 'kind': 'pose', 'pos': [2.369, 1.532, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 105.0, 'kind': 'pose', 'pos': [2.557, 1.481, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 106.0, 'kind': 'pose', 'pos': [2.857, 1.477, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 107.0, 'kind': 'pose', 'pos': [3.081, 1.369, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 108.0, 'kind': 'pose', 'pos': [3.272, 1.178, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 109.0, 'kind': 'pose', 'pos': [3.442, 1.008, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 110.0, 'kind': 'pose', 'pos': [3.611, 0.839, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 111.0, 'kind': 'pose', 'pos': [3.846, 0.754, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 112.0, 'kind': 'pose', 'pos': [3.783, 0.54, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 113.0, 'kind': 'pose', 'pos': [3.604, 0.39, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 114.0, 'kind': 'pose', 'pos': [3.346, 0.341, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 115.0, 'kind': 'pose', 'pos': [3.125, 0.325, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 116.0, 'kind': 'pose', 'pos': [2.929, 0.431, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 117.0, 'kind': 'pose', 'pos': [2.738, 0.41, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 118.0, 'kind': 'pose', 'pos': [2.653, 0.283, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 119.0, 'kind': 'pose', 'pos': [2.591, 0.274, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 120.0, 'kind': 'pose', 'pos': [2.643, 0.352, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 121.0, 'kind': 'pose', 'pos': [2.875, 0.325, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 122.0, 'kind': 'pose', 'pos': [2.633, 0.367, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 123.0, 'kind': 'pose', 'pos': [2.675, 0.325, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 124.0, 'kind': 'pose', 'pos': [2.975, 0.325, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 125.0, 'kind': 'pose', 'pos': [3.275, 0.325, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 126.0, 'kind': 'pose', 'pos': [3.545, 0.325, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 127.0, 'kind': 'pose', 'pos': [3.845, 0.325, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 128.0, 'kind': 'pose', 'pos': [4.054, 0.346, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 129.0, 'kind': 'pose', 'pos': [3.842, 0.558, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 130.0, 'kind': 'pose', 'pos': [3.733, 0.717, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 131.0, 'kind': 'pose', 'pos': [3.598, 0.902, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 132.0, 'kind': 'pose', 'pos': [3.337, 0.924, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 133.0, 'kind': 'pose', 'pos': [3.037, 0.925, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 134.0, 'kind': 'pose', 'pos': [2.861, 1.089, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 135.0, 'kind': 'pose', 'pos': [2.67, 1.28, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 136.0, 'kind': 'pose', 'pos': [2.479, 1.471, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 137.0, 'kind': 'pose', 'pos': [2.292, 1.609, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 138.0, 'kind': 'pose', 'pos': [2.225, 1.822, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 139.0, 'kind': 'pose', 'pos': [2.287, 2.031, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 140.0, 'kind': 'pose', 'pos': [2.519, 2.122, -0.531], 'state': 'moving', 'level': 'B1'},
        {'t': 141.0, 'kind': 'pose', 'pos': [2.756, 2.043, -0.602], 'state': 'moving', 'level': 'ramp'},
        {'t': 142.0, 'kind': 'pose', 'pos': [2.775, 2.085, -0.607], 'state': 'moving', 'level': 'ramp'},
        {'t': 143.0, 'kind': 'pose', 'pos': [2.949, 2.039, -0.66], 'state': 'moving', 'level': 'ramp'},
        {'t': 144.0, 'kind': 'pose', 'pos': [3.119, 2.082, -0.711], 'state': 'moving', 'level': 'ramp'},
        {'t': 145.0, 'kind': 'pose', 'pos': [3.289, 2.124, -0.762], 'state': 'arrived', 'level': 'ramp'},
        {'t': 146.0, 'kind': 'pose', 'pos': [3.352, 1.975, -0.781], 'state': 'blocked', 'level': 'ramp'},
        {'t': 147.0, 'kind': 'pose', 'pos': [3.478, 2.169, -0.818], 'state': 'arrived', 'level': 'ramp'},
        {'t': 148.0, 'kind': 'pose', 'pos': [3.669, 1.978, -0.876], 'state': 'moving', 'level': 'ramp'},
        {'t': 149.0, 'kind': 'pose', 'pos': [3.546, 2.096, -0.839], 'state': 'moving', 'level': 'ramp'},
        {'t': 150.0, 'kind': 'pose', 'pos': [3.717, 2.182, -0.89], 'state': 'arrived', 'level': 'ramp'},
        {'t': 151.0, 'kind': 'pose', 'pos': [3.823, 2.196, -0.922], 'state': 'moving', 'level': 'ramp'},
        {'t': 152.0, 'kind': 'pose', 'pos': [3.925, 2.075, -0.952], 'state': 'moving', 'level': 'ramp'},
        {'t': 153.0, 'kind': 'pose', 'pos': [3.875, 1.975, -0.937], 'state': 'arrived', 'level': 'ramp'},
        {'t': 154.0, 'kind': 'pose', 'pos': [4.065, 2.075, -0.994], 'state': 'moving', 'level': 'ramp'},
        {'t': 155.0, 'kind': 'pose', 'pos': [4.365, 2.075, -1.084], 'state': 'moving', 'level': 'ramp'},
        {'t': 155.3, 'kind': 'level', 'level': 'B2'},
        {'t': 156.0, 'kind': 'pose', 'pos': [4.6, 1.99, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 157.0, 'kind': 'pose', 'pos': [4.727, 2.015, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 158.0, 'kind': 'pose', 'pos': [4.725, 1.715, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 159.0, 'kind': 'pose', 'pos': [4.598, 1.498, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 160.0, 'kind': 'pose', 'pos': [4.337, 1.476, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 161.0, 'kind': 'pose', 'pos': [4.037, 1.476, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 162.0, 'kind': 'pose', 'pos': [3.737, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 163.0, 'kind': 'pose', 'pos': [3.467, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 164.0, 'kind': 'pose', 'pos': [3.167, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 165.0, 'kind': 'pose', 'pos': [2.867, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 166.0, 'kind': 'pose', 'pos': [2.575, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 167.0, 'kind': 'pose', 'pos': [2.427, 1.327, -1.125], 'state': 'blocked', 'level': 'B2'},
        {'t': 168.0, 'kind': 'pose', 'pos': [2.484, 1.515, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 169.0, 'kind': 'pose', 'pos': [2.254, 1.504, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 170.0, 'kind': 'pose', 'pos': [2.025, 1.475, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 171.0, 'kind': 'pose', 'pos': [1.84, 1.34, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 172.0, 'kind': 'pose', 'pos': [1.67, 1.17, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 173.0, 'kind': 'pose', 'pos': [1.501, 1.001, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 174.0, 'kind': 'pose', 'pos': [1.463, 1.165, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 175.0, 'kind': 'pose', 'pos': [1.567, 1.033, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 176.0, 'kind': 'pose', 'pos': [1.44, 0.84, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 177.0, 'kind': 'pose', 'pos': [1.228, 0.628, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 178.0, 'kind': 'pose', 'pos': [1.004, 0.646, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 179.0, 'kind': 'pose', 'pos': [0.819, 0.781, -1.125], 'state': 'moving', 'level': 'B2'},
    ],
    'b3-0': [
        {'t': 0.0, 'kind': 'level', 'level': 'L1'},
        {'t': 0.0, 'kind': 'pose', 'pos': [0.5, 0.5, 0.675], 'state': 'idle', 'level': 'L1'},
        {'t': 1.0, 'kind': 'pose', 'pos': [0.507, 0.8, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 2.0, 'kind': 'pose', 'pos': [0.515, 1.1, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 3.0, 'kind': 'pose', 'pos': [0.522, 1.4, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 4.0, 'kind': 'pose', 'pos': [0.645, 1.525, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 5.0, 'kind': 'pose', 'pos': [0.852, 1.652, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 6.0, 'kind': 'pose', 'pos': [1.022, 1.822, 0.675], 'state': 'arrived', 'level': 'L1'},
        {'t': 7.0, 'kind': 'pose', 'pos': [1.23, 1.973, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 8.0, 'kind': 'pose', 'pos': [1.424, 2.025, 0.675], 'state': 'moving', 'level': 'L1'},
        {'t': 9.0, 'kind': 'pose', 'pos': [1.647, 2.068, 0.631], 'state': 'moving', 'level': 'ramp'},
        {'t': 10.0, 'kind': 'pose', 'pos': [1.947, 2.071, 0.541], 'state': 'moving', 'level': 'ramp'},
        {'t': 11.0, 'kind': 'pose', 'pos': [2.247, 2.073, 0.451], 'state': 'moving', 'level': 'ramp'},
        {'t': 12.0, 'kind': 'pose', 'pos': [2.499, 2.032, 0.375], 'state': 'moving', 'level': 'ramp'},
        {'t': 13.0, 'kind': 'pose', 'pos': [2.669, 2.075, 0.324], 'state': 'arrived', 'level': 'ramp'},
        {'t': 14.0, 'kind': 'pose', 'pos': [2.775, 2.025, 0.293], 'state': 'arrived', 'level': 'ramp'},
        {'t': 15.0, 'kind': 'pose', 'pos': [2.796, 2.087, 0.286], 'state': 'moving', 'level': 'ramp'},
        {'t': 16.0, 'kind': 'pose', 'pos': [2.981, 2.069, 0.231], 'state': 'moving', 'level': 'ramp'},
        {'t': 17.0, 'kind': 'pose', 'pos': [3.081, 1.992, 0.201], 'state': 'moving', 'level': 'ramp'},
        {'t': 18.0, 'kind': 'pose', 'pos': [3.057, 2.041, 0.208], 'state': 'moving', 'level': 'ramp'},
        {'t': 19.0, 'kind': 'pose', 'pos': [3.239, 2.111, 0.153], 'state': 'moving', 'level': 'ramp'},
        {'t': 20.0, 'kind': 'pose', 'pos': [3.387, 1.963, 0.109], 'state': 'blocked', 'level': 'ramp'},
        {'t': 21.0, 'kind': 'pose', 'pos': [3.337, 2.019, 0.124], 'state': 'moving', 'level': 'ramp'},
        {'t': 21.6, 'kind': 'level', 'level': 'ground'},
        {'t': 22.0, 'kind': 'pose', 'pos': [3.496, 2.154, 0.076], 'state': 'moving', 'level': 'ground'},
        {'t': 23.0, 'kind': 'pose', 'pos': [3.687, 2.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 24.0, 'kind': 'pose', 'pos': [3.676, 2.091, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 25.0, 'kind': 'pose', 'pos': [3.744, 1.912, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 26.0, 'kind': 'pose', 'pos': [3.725, 1.725, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 27.0, 'kind': 'pose', 'pos': [3.654, 1.554, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 28.0, 'kind': 'pose', 'pos': [3.473, 1.482, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 29.0, 'kind': 'pose', 'pos': [3.173, 1.48, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 30.0, 'kind': 'pose', 'pos': [2.873, 1.478, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 31.0, 'kind': 'pose', 'pos': [2.573, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 32.0, 'kind': 'pose', 'pos': [2.303, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 33.0, 'kind': 'pose', 'pos': [2.003, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 34.0, 'kind': 'pose', 'pos': [1.703, 1.475, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 35.0, 'kind': 'pose', 'pos': [1.475, 1.475, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 36.0, 'kind': 'pose', 'pos': [1.475, 1.175, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 37.0, 'kind': 'pose', 'pos': [1.39, 0.94, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 38.0, 'kind': 'pose', 'pos': [1.225, 0.805, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 39.0, 'kind': 'pose', 'pos': [1.165, 1.022, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 40.0, 'kind': 'pose', 'pos': [0.98, 1.219, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 41.0, 'kind': 'pose', 'pos': [1.148, 1.266, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 42.0, 'kind': 'pose', 'pos': [1.448, 1.272, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 43.0, 'kind': 'pose', 'pos': [1.715, 1.275, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 44.0, 'kind': 'pose', 'pos': [2.015, 1.275, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 45.0, 'kind': 'pose', 'pos': [2.315, 1.275, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 46.0, 'kind': 'pose', 'pos': [2.585, 1.275, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 47.0, 'kind': 'pose', 'pos': [2.875, 1.275, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 48.0, 'kind': 'pose', 'pos': [3.074, 1.172, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 49.0, 'kind': 'pose', 'pos': [3.267, 0.983, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 50.0, 'kind': 'pose', 'pos': [3.475, 0.975, 0.075], 'state': 'arrived', 'level': 'ground'},
        {'t': 51.0, 'kind': 'pose', 'pos': [3.709, 0.788, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 52.0, 'kind': 'pose', 'pos': [3.775, 0.625, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 53.0, 'kind': 'pose', 'pos': [3.661, 0.461, 0.075], 'state': 'moving', 'level': 'ground'},
        {'t': 54.0, 'kind': 'pose', 'pos': [3.483, 0.333, 0.07], 'state': 'moving', 'level': 'ground'},
        {'t': 55.0, 'kind': 'pose', 'pos': [3.213, 0.331, -0.011], 'state': 'moving', 'level': 'ramp'},
        {'t': 56.0, 'kind': 'pose', 'pos': [2.913, 0.328, -0.101], 'state': 'moving', 'level': 'ramp'},
        {'t': 57.0, 'kind': 'pose', 'pos': [2.613, 0.326, -0.191], 'state': 'moving', 'level': 'ramp'},
        {'t': 58.0, 'kind': 'pose', 'pos': [2.387, 0.431, -0.259], 'state': 'moving', 'level': 'ramp'},
        {'t': 59.0, 'kind': 'pose', 'pos': [2.36, 0.405, -0.267], 'state': 'moving', 'level': 'ramp'},
        {'t': 60.0, 'kind': 'pose', 'pos': [2.275, 0.225, -0.292], 'state': 'moving', 'level': 'ramp'},
        {'t': 61.0, 'kind': 'pose', 'pos': [2.105, 0.395, -0.343], 'state': 'moving', 'level': 'ramp'},
        {'t': 62.0, 'kind': 'pose', 'pos': [2.075, 0.325, -0.352], 'state': 'arrived', 'level': 'ramp'},
        {'t': 63.0, 'kind': 'pose', 'pos': [1.975, 0.375, -0.382], 'state': 'moving', 'level': 'ramp'},
        {'t': 64.0, 'kind': 'pose', 'pos': [1.833, 0.317, -0.425], 'state': 'arrived', 'level': 'ramp'},
        {'t': 65.0, 'kind': 'pose', 'pos': [1.598, 0.402, -0.496], 'state': 'moving', 'level': 'ramp'},
        {'t': 65.9, 'kind': 'level', 'level': 'B1'},
        {'t': 66.0, 'kind': 'pose', 'pos': [1.531, 0.373, -0.516], 'state': 'moving', 'level': 'B1'},
        {'t': 67.0, 'kind': 'pose', 'pos': [1.489, 0.415, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 68.0, 'kind': 'pose', 'pos': [1.378, 0.403, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 69.0, 'kind': 'pose', 'pos': [1.227, 0.573, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 70.0, 'kind': 'pose', 'pos': [1.209, 0.689, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 71.0, 'kind': 'pose', 'pos': [1.367, 0.817, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 72.0, 'kind': 'pose', 'pos': [1.374, 0.885, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 73.0, 'kind': 'pose', 'pos': [1.548, 0.958, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 74.0, 'kind': 'pose', 'pos': [1.581, 1.149, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 75.0, 'kind': 'pose', 'pos': [1.411, 1.319, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 76.0, 'kind': 'pose', 'pos': [1.22, 1.51, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 77.0, 'kind': 'pose', 'pos': [1.033, 1.637, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 78.0, 'kind': 'pose', 'pos': [0.793, 1.637, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 79.0, 'kind': 'pose', 'pos': [0.806, 1.471, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 80.0, 'kind': 'pose', 'pos': [0.616, 1.395, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 81.0, 'kind': 'pose', 'pos': [0.42, 1.58, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 82.0, 'kind': 'pose', 'pos': [0.39, 1.58, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 83.0, 'kind': 'pose', 'pos': [0.164, 1.686, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 84.0, 'kind': 'pose', 'pos': [0.333, 1.517, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 85.0, 'kind': 'pose', 'pos': [0.535, 1.375, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 86.0, 'kind': 'pose', 'pos': [0.78, 1.437, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 87.0, 'kind': 'pose', 'pos': [0.974, 1.625, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 88.0, 'kind': 'pose', 'pos': [1.022, 1.837, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 89.0, 'kind': 'pose', 'pos': [1.205, 1.925, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 90.0, 'kind': 'pose', 'pos': [1.505, 1.925, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 91.0, 'kind': 'pose', 'pos': [1.775, 1.925, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 92.0, 'kind': 'pose', 'pos': [2.075, 1.925, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 93.0, 'kind': 'pose', 'pos': [2.295, 1.903, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 94.0, 'kind': 'pose', 'pos': [2.225, 1.695, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 95.0, 'kind': 'pose', 'pos': [2.373, 1.527, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 96.0, 'kind': 'pose', 'pos': [2.587, 1.481, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 97.0, 'kind': 'pose', 'pos': [2.887, 1.476, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 98.0, 'kind': 'pose', 'pos': [3.069, 1.33, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 99.0, 'kind': 'pose', 'pos': [3.26, 1.139, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 100.0, 'kind': 'pose', 'pos': [3.239, 0.926, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 101.0, 'kind': 'pose', 'pos': [3.175, 0.975, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 102.0, 'kind': 'pose', 'pos': [3.397, 1.025, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 103.0, 'kind': 'pose', 'pos': [3.595, 0.855, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 104.0, 'kind': 'pose', 'pos': [3.775, 0.675, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 105.0, 'kind': 'pose', 'pos': [3.725, 0.525, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 106.0, 'kind': 'pose', 'pos': [3.796, 0.604, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 107.0, 'kind': 'pose', 'pos': [3.832, 0.434, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 108.0, 'kind': 'pose', 'pos': [3.675, 0.375, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 109.0, 'kind': 'pose', 'pos': [3.574, 0.391, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 110.0, 'kind': 'pose', 'pos': [3.395, 0.325, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 111.0, 'kind': 'pose', 'pos': [3.225, 0.427, -0.525], 'state': 'blocked', 'level': 'B1'},
        {'t': 112.0, 'kind': 'pose', 'pos': [3.154, 0.296, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 113.0, 'kind': 'pose', 'pos': [3.069, 0.381, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 114.0, 'kind': 'pose', 'pos': [2.829, 0.381, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 115.0, 'kind': 'pose', 'pos': [2.642, 0.296, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 116.0, 'kind': 'pose', 'pos': [2.625, 0.375, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 117.0, 'kind': 'pose', 'pos': [2.781, 0.269, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 118.0, 'kind': 'pose', 'pos': [3.051, 0.27, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 119.0, 'kind': 'pose', 'pos': [3.351, 0.271, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 120.0, 'kind': 'pose', 'pos': [3.651, 0.273, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 121.0, 'kind': 'pose', 'pos': [3.921, 0.275, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 122.0, 'kind': 'pose', 'pos': [3.775, 0.485, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 123.0, 'kind': 'pose', 'pos': [3.737, 0.711, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 124.0, 'kind': 'pose', 'pos': [3.579, 0.921, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 125.0, 'kind': 'pose', 'pos': [3.385, 0.966, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 126.0, 'kind': 'pose', 'pos': [3.193, 1.024, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 127.0, 'kind': 'pose', 'pos': [2.99, 1.11, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 128.0, 'kind': 'pose', 'pos': [2.799, 1.301, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 129.0, 'kind': 'pose', 'pos': [2.63, 1.47, -0.525], 'state': 'arrived', 'level': 'B1'},
        {'t': 130.0, 'kind': 'pose', 'pos': [2.383, 1.517, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 131.0, 'kind': 'pose', 'pos': [2.229, 1.726, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 132.0, 'kind': 'pose', 'pos': [2.267, 1.917, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 133.0, 'kind': 'pose', 'pos': [2.446, 2.046, -0.525], 'state': 'moving', 'level': 'B1'},
        {'t': 134.0, 'kind': 'pose', 'pos': [2.707, 2.069, -0.587], 'state': 'moving', 'level': 'ramp'},
        {'t': 135.0, 'kind': 'pose', 'pos': [3.007, 2.071, -0.677], 'state': 'moving', 'level': 'ramp'},
        {'t': 136.0, 'kind': 'pose', 'pos': [3.307, 2.074, -0.767], 'state': 'moving', 'level': 'ramp'},
        {'t': 137.0, 'kind': 'pose', 'pos': [3.542, 1.99, -0.838], 'state': 'moving', 'level': 'ramp'},
        {'t': 138.0, 'kind': 'pose', 'pos': [3.712, 2.117, -0.889], 'state': 'moving', 'level': 'ramp'},
        {'t': 139.0, 'kind': 'pose', 'pos': [3.776, 2.031, -0.908], 'state': 'arrived', 'level': 'ramp'},
        {'t': 140.0, 'kind': 'pose', 'pos': [3.675, 1.975, -0.877], 'state': 'moving', 'level': 'ramp'},
        {'t': 141.0, 'kind': 'pose', 'pos': [3.865, 2.075, -0.934], 'state': 'moving', 'level': 'ramp'},
        {'t': 142.0, 'kind': 'pose', 'pos': [4.165, 2.075, -1.024], 'state': 'moving', 'level': 'ramp'},
        {'t': 142.9, 'kind': 'level', 'level': 'B2'},
        {'t': 143.0, 'kind': 'pose', 'pos': [4.465, 2.075, -1.114], 'state': 'moving', 'level': 'B2'},
        {'t': 144.0, 'kind': 'pose', 'pos': [4.652, 1.99, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 145.0, 'kind': 'pose', 'pos': [4.587, 2.075, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 146.0, 'kind': 'pose', 'pos': [4.317, 2.075, -1.07], 'state': 'moving', 'level': 'ramp'},
        {'t': 147.0, 'kind': 'pose', 'pos': [4.095, 2.117, -1.003], 'state': 'moving', 'level': 'ramp'},
        {'t': 148.0, 'kind': 'pose', 'pos': [4.065, 2.046, -0.994], 'state': 'moving', 'level': 'ramp'},
        {'t': 149.0, 'kind': 'pose', 'pos': [4.225, 2.075, -1.042], 'state': 'arrived', 'level': 'ramp'},
        {'t': 150.0, 'kind': 'pose', 'pos': [4.485, 2.075, -1.12], 'state': 'moving', 'level': 'B2'},
        {'t': 151.0, 'kind': 'pose', 'pos': [4.689, 1.909, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 152.0, 'kind': 'pose', 'pos': [4.725, 1.665, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 153.0, 'kind': 'pose', 'pos': [4.581, 1.482, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 154.0, 'kind': 'pose', 'pos': [4.281, 1.48, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 155.0, 'kind': 'pose', 'pos': [3.981, 1.478, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 156.0, 'kind': 'pose', 'pos': [3.681, 1.476, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 157.0, 'kind': 'pose', 'pos': [3.411, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 158.0, 'kind': 'pose', 'pos': [3.111, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 159.0, 'kind': 'pose', 'pos': [2.811, 1.475, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 160.0, 'kind': 'pose', 'pos': [2.568, 1.411, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 161.0, 'kind': 'pose', 'pos': [2.372, 1.311, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 162.0, 'kind': 'pose', 'pos': [2.525, 1.425, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 163.0, 'kind': 'pose', 'pos': [2.383, 1.567, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 164.0, 'kind': 'pose', 'pos': [2.167, 1.514, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 165.0, 'kind': 'pose', 'pos': [1.998, 1.348, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 166.0, 'kind': 'pose', 'pos': [1.807, 1.369, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 167.0, 'kind': 'pose', 'pos': [1.567, 1.369, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 168.0, 'kind': 'pose', 'pos': [1.38, 1.454, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 169.0, 'kind': 'pose', 'pos': [1.189, 1.263, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 170.0, 'kind': 'pose', 'pos': [1.019, 1.093, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 171.0, 'kind': 'pose', 'pos': [0.775, 1.075, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 172.0, 'kind': 'pose', 'pos': [0.579, 0.969, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 173.0, 'kind': 'pose', 'pos': [0.339, 0.969, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 174.0, 'kind': 'pose', 'pos': [0.173, 1.075, -1.125], 'state': 'blocked', 'level': 'B2'},
        {'t': 175.0, 'kind': 'pose', 'pos': [0.36, 1.09, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 176.0, 'kind': 'pose', 'pos': [0.354, 0.904, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 177.0, 'kind': 'pose', 'pos': [0.163, 0.84, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 178.0, 'kind': 'pose', 'pos': [0.275, 0.822, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 179.0, 'kind': 'pose', 'pos': [0.225, 0.925, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 180.0, 'kind': 'pose', 'pos': [0.447, 0.875, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 181.0, 'kind': 'pose', 'pos': [0.623, 0.727, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 182.0, 'kind': 'pose', 'pos': [0.867, 0.683, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 183.0, 'kind': 'pose', 'pos': [0.996, 0.504, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 184.0, 'kind': 'pose', 'pos': [0.975, 0.325, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 185.0, 'kind': 'pose', 'pos': [0.804, 0.202, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 186.0, 'kind': 'pose', 'pos': [1.001, 0.314, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 187.0, 'kind': 'pose', 'pos': [1.125, 0.525, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 188.0, 'kind': 'pose', 'pos': [1.167, 0.717, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 189.0, 'kind': 'pose', 'pos': [1.38, 0.93, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 190.0, 'kind': 'pose', 'pos': [1.57, 1.12, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 191.0, 'kind': 'pose', 'pos': [1.761, 1.311, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 192.0, 'kind': 'pose', 'pos': [1.925, 1.475, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 193.0, 'kind': 'pose', 'pos': [2.146, 1.496, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 194.0, 'kind': 'pose', 'pos': [2.345, 1.575, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 195.0, 'kind': 'pose', 'pos': [2.552, 1.448, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 196.0, 'kind': 'pose', 'pos': [2.764, 1.236, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 197.0, 'kind': 'pose', 'pos': [3.034, 1.23, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 198.0, 'kind': 'pose', 'pos': [3.325, 1.225, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 199.0, 'kind': 'pose', 'pos': [3.595, 1.225, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 200.0, 'kind': 'pose', 'pos': [3.865, 1.225, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 201.0, 'kind': 'pose', 'pos': [4.087, 1.204, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 202.0, 'kind': 'pose', 'pos': [4.282, 1.018, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 203.0, 'kind': 'pose', 'pos': [4.517, 0.927, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 204.0, 'kind': 'pose', 'pos': [4.723, 0.777, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 205.0, 'kind': 'pose', 'pos': [4.725, 0.537, -1.125], 'state': 'arrived', 'level': 'B2'},
        {'t': 206.0, 'kind': 'pose', 'pos': [4.525, 0.375, -1.125], 'state': 'moving', 'level': 'B2'},
        {'t': 207.0, 'kind': 'pose', 'pos': [4.303, 0.331, -1.184], 'state': 'moving', 'level': 'ramp'},
        {'t': 208.0, 'kind': 'pose', 'pos': [4.003, 0.329, -1.274], 'state': 'moving', 'level': 'ramp'},
        {'t': 209.0, 'kind': 'pose', 'pos': [3.703, 0.327, -1.364], 'state': 'moving', 'level': 'ramp'},
        {'t': 210.0, 'kind': 'pose', 'pos': [3.45, 0.368, -1.44], 'state': 'moving', 'level': 'ramp'},
        {'t': 211.0, 'kind': 'pose', 'pos': [3.354, 0.396, -1.469], 'state': 'moving', 'level': 'ramp'},
        {'t': 212.0, 'kind': 'pose', 'pos': [3.41, 0.3, -1.452], 'state': 'moving', 'level': 'ramp'},
        {'t': 213.0, 'kind': 'pose', 'pos': [3.238, 0.272, -1.504], 'state': 'moving', 'level': 'ramp'},
        {'t': 214.0, 'kind': 'pose', 'pos': [3.069, 0.431, -1.554], 'state': 'arrived', 'level': 'ramp'},
        {'t': 215.0, 'kind': 'pose', 'pos': [2.92, 0.367, -1.599], 'state': 'moving', 'level': 'ramp'},
        {'t': 216.0, 'kind': 'pose', 'pos': [2.751, 0.325, -1.65], 'state': 'arrived', 'level': 'ramp'},
        {'t': 217.0, 'kind': 'level', 'level': 'B3'},
        {'t': 217.0, 'kind': 'pose', 'pos': [2.56, 0.304, -1.707], 'state': 'moving', 'level': 'B3'},
        {'t': 218.0, 'kind': 'pose', 'pos': [2.39, 0.389, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 219.0, 'kind': 'pose', 'pos': [2.22, 0.431, -1.725], 'state': 'arrived', 'level': 'B3'},
        {'t': 220.0, 'kind': 'pose', 'pos': [1.986, 0.346, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 221.0, 'kind': 'pose', 'pos': [1.816, 0.261, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 222.0, 'kind': 'pose', 'pos': [1.572, 0.325, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 223.0, 'kind': 'pose', 'pos': [1.302, 0.325, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 224.0, 'kind': 'pose', 'pos': [1.002, 0.325, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 225.0, 'kind': 'pose', 'pos': [0.827, 0.473, -1.725], 'state': 'arrived', 'level': 'B3'},
        {'t': 226.0, 'kind': 'pose', 'pos': [0.678, 0.652, -1.725], 'state': 'blocked', 'level': 'B3'},
        {'t': 227.0, 'kind': 'pose', 'pos': [0.875, 0.625, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 228.0, 'kind': 'pose', 'pos': [1.024, 0.803, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 229.0, 'kind': 'pose', 'pos': [1.024, 1.103, -1.725], 'state': 'moving', 'level': 'B3'},
        {'t': 230.0, 'kind': 'pose', 'pos': [0.984, 1.357, -1.725], 'state': 'moving', 'level': 'B3'},
    ],
}


def stops(records):
    """[(t, state, logged level, its floor, problem or None)] for every stop."""
    out, floor = [], None
    for r in records:
        if r.get("kind") == "level":
            floor = r["level"]
            continue
        if r.get("kind") != "pose" or r.get("state") == MOVING:
            continue
        level, z = r.get("level"), r["pos"][2] - RIDE
        problem = None
        if floor not in FLOOR_Z:
            problem = "no floor reached yet"
        elif level in FLOOR_Z:
            if level != floor:
                problem = f"names {level} while on {floor}"
            elif abs(z - FLOOR_Z[floor]) > Z_TOL:
                problem = f"at z {z:.3f}, not {floor}'s {FLOOR_Z[floor]}"
        elif level == "ramp":
            i = ORDER.index(floor)
            below = (FLOOR_Z[ORDER[i + 1]], FLOOR_Z[floor]) if i + 1 < len(ORDER) else None
            above = (FLOOR_Z[floor], FLOOR_Z[ORDER[i - 1]]) if i > 0 else None
            if not any(span and span[0] < z < span[1] for span in (below, above)):
                problem = f"on a ramp at z {z:.3f}, on neither ramp next to {floor}"
        else:
            problem = f"level {level!r} names no floor"
        out.append((r["t"], r.get("state"), level, floor, problem))
    return out


def check(records):
    got = stops(records)
    assert got, "no stop in this log"
    bad = [s for s in got if s[4]]
    assert bad == [], bad
    return got


@pytest.mark.parametrize("name,n_stops,on_ramp", [("b2-0", 29, 13), ("b3-0", 40, 9)])
def test_real_logs_every_stop_is_on_its_floor(name, n_stops, on_ramp):
    got = check(REAL[name])
    assert len(got) == n_stops
    assert sum(1 for s in got if s[2] == "ramp") == on_ramp           # the finding in the docstring
    floors = {s[3] for s in got}
    assert floors == set(ORDER[:len(floors)])                      # stops on every floor on the way down


@pytest.mark.parametrize("name", ["b2", "b3"])
def test_full_real_logs(name):
    env = os.environ.get(f"{name.upper()}_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "runs").glob(f"{name}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip(f"no full {name.upper()} log")
    records = [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    print(name, len(check(records)), "stops placed")


def _stop(**kv):
    return {"t": 5.0, "kind": "pose", "state": "arrived", "pos": [1.0, 1.0, 0.0 + RIDE], "level": "ground", **kv}


@pytest.mark.parametrize("records,word", [
    ([{"t": 0, "kind": "level", "level": "ground"}, _stop(level="B1", pos=[1, 1, -0.6 + RIDE])], "names"),
    ([{"t": 0, "kind": "level", "level": "ground"}, _stop(pos=[1, 1, -0.3])], "at z"),
    ([{"t": 0, "kind": "level", "level": "B1"}, _stop(level="ramp", pos=[1, 1, 0.9])], "ramp"),   # two floors up
    ([{"t": 0, "kind": "level", "level": "ground"}, _stop(level="B9")], "names no floor"),
    ([_stop()], "no floor reached"),
])
def test_unplaceable_stops_fail(records, word):
    problems = [s[4] for s in stops(records) if s[4]]
    assert problems and word in problems[0], problems
    with pytest.raises(AssertionError):
        check(records)


def test_a_stop_back_up_the_ramp_it_came_down_is_placed():
    recs = [{"t": 0, "kind": "level", "level": "B2"}, _stop(level="ramp", pos=[1, 1, -1.042])]   # z -1.117
    assert stops(recs)[0][4] is None


def test_the_real_b3_climb_back_is_in_the_log():
    s = next(x for x in stops(REAL["b3-0"]) if x[0] == 149.0)
    assert s[2] == "ramp" and s[3] == "B2" and s[4] is None


def test_a_moving_pose_is_not_a_stop():
    recs = [{"t": 0, "kind": "level", "level": "ground"}, _stop(state="moving", level="ramp", pos=[1, 1, 5.0])]
    assert stops(recs) == []
