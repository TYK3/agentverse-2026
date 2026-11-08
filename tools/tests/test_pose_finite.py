"""POSE-FINITE: every pose in a real run log is finite and well formed (ref b3).

Each `pose` record of a tools/run_b2.py log (1 Hz) must have:
- t: a finite number >= 0, never going back from one pose to the next;
- pos: three finite numbers, inside the levels building's bounds (BOUNDS: x, y over the site, z between
  B3 and L1 plus the Scout's ride height);
- cell: three ints, consistent with pos on the 0.05 m grid: i = floor(x / 0.05), j = floor(y / 0.05),
  k = round((z - RIDE) / 0.05), to within one cell (pos is logged rounded to the millimetre while
  the cell comes from the unrounded position, so 0.79999 m logs as pos 0.8 with cell 15);
- state: one of the Scout's motion states; level: a floor name or "ramp".
No NaN or infinity anywhere, as JSON would carry them (python's json writes NaN and Infinity unquoted).

Real log: REAL_B3_POSES, every pose of a real B3 run (seed 0 on main, 9/9, 231 poses, L1 to B3), and,
when available, the newest full runs/b2-*.jsonl and runs/b3-*.jsonl (or $B2_LOG / $B3_LOG); those skip
otherwise (CI has none).
"""

import json
import math
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RES = 0.05
RIDE = 0.075                                           # the Scout rides this far above the floor
STATES = {"idle", "moving", "arrived", "blocked", "frozen"}
LEVELS = {"L1", "ground", "B1", "B2", "B3", "ramp"}
BOUNDS = ((-1.0, 6.0), (-1.0, 4.0), (-1.8 - 0.1, 0.6 + RIDE + 0.1))   # x, y, z (metres)

REAL_B3_POSES = [
    {'t': 0.0, 'kind': 'pose', 'pos': [0.5, 0.5, 0.675], 'state': 'idle', 'level': 'L1', 'cell': [10, 10, 12]},
    {'t': 1.0, 'kind': 'pose', 'pos': [0.507, 0.8, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [10, 15, 12]},
    {'t': 2.0, 'kind': 'pose', 'pos': [0.515, 1.1, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [10, 21, 12]},
    {'t': 3.0, 'kind': 'pose', 'pos': [0.522, 1.4, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [10, 27, 12]},
    {'t': 4.0, 'kind': 'pose', 'pos': [0.645, 1.525, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [12, 30, 12]},
    {'t': 5.0, 'kind': 'pose', 'pos': [0.852, 1.652, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [17, 33, 12]},
    {'t': 6.0, 'kind': 'pose', 'pos': [1.022, 1.822, 0.675], 'state': 'arrived', 'level': 'L1', 'cell': [20, 36, 12]},
    {'t': 7.0, 'kind': 'pose', 'pos': [1.23, 1.973, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [24, 39, 12]},
    {'t': 8.0, 'kind': 'pose', 'pos': [1.424, 2.025, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [28, 40, 12]},
    {'t': 9.0, 'kind': 'pose', 'pos': [1.647, 2.068, 0.631], 'state': 'moving', 'level': 'ramp', 'cell': [32, 41, 11]},
    {'t': 10.0, 'kind': 'pose', 'pos': [1.947, 2.071, 0.541], 'state': 'moving', 'level': 'ramp', 'cell': [38, 41, 9]},
    {'t': 11.0, 'kind': 'pose', 'pos': [2.247, 2.073, 0.451], 'state': 'moving', 'level': 'ramp', 'cell': [44, 41, 8]},
    {'t': 12.0, 'kind': 'pose', 'pos': [2.499, 2.032, 0.375], 'state': 'moving', 'level': 'ramp', 'cell': [49, 40, 6]},
    {'t': 13.0, 'kind': 'pose', 'pos': [2.669, 2.075, 0.324], 'state': 'arrived', 'level': 'ramp', 'cell': [53, 41, 5]},
    {'t': 14.0, 'kind': 'pose', 'pos': [2.775, 2.025, 0.293], 'state': 'arrived', 'level': 'ramp', 'cell': [55, 40, 4]},
    {'t': 15.0, 'kind': 'pose', 'pos': [2.796, 2.087, 0.286], 'state': 'moving', 'level': 'ramp', 'cell': [55, 41, 4]},
    {'t': 16.0, 'kind': 'pose', 'pos': [2.981, 2.069, 0.231], 'state': 'moving', 'level': 'ramp', 'cell': [59, 41, 3]},
    {'t': 17.0, 'kind': 'pose', 'pos': [3.081, 1.992, 0.201], 'state': 'moving', 'level': 'ramp', 'cell': [61, 39, 3]},
    {'t': 18.0, 'kind': 'pose', 'pos': [3.057, 2.041, 0.208], 'state': 'moving', 'level': 'ramp', 'cell': [61, 40, 3]},
    {'t': 19.0, 'kind': 'pose', 'pos': [3.239, 2.111, 0.153], 'state': 'moving', 'level': 'ramp', 'cell': [64, 42, 2]},
    {'t': 20.0, 'kind': 'pose', 'pos': [3.387, 1.963, 0.109], 'state': 'blocked', 'level': 'ramp', 'cell': [67, 39, 1]},
    {'t': 21.0, 'kind': 'pose', 'pos': [3.337, 2.019, 0.124], 'state': 'moving', 'level': 'ramp', 'cell': [66, 40, 1]},
    {'t': 22.0, 'kind': 'pose', 'pos': [3.496, 2.154, 0.076], 'state': 'moving', 'level': 'ground', 'cell': [69, 43, 0]},
    {'t': 23.0, 'kind': 'pose', 'pos': [3.687, 2.175, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [73, 43, 0]},
    {'t': 24.0, 'kind': 'pose', 'pos': [3.676, 2.091, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [73, 41, 0]},
    {'t': 25.0, 'kind': 'pose', 'pos': [3.744, 1.912, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [74, 38, 0]},
    {'t': 26.0, 'kind': 'pose', 'pos': [3.725, 1.725, 0.075], 'state': 'arrived', 'level': 'ground', 'cell': [74, 34, 0]},
    {'t': 27.0, 'kind': 'pose', 'pos': [3.654, 1.554, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [73, 31, 0]},
    {'t': 28.0, 'kind': 'pose', 'pos': [3.473, 1.482, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [69, 29, 0]},
    {'t': 29.0, 'kind': 'pose', 'pos': [3.173, 1.48, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [63, 29, 0]},
    {'t': 30.0, 'kind': 'pose', 'pos': [2.873, 1.478, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [57, 29, 0]},
    {'t': 31.0, 'kind': 'pose', 'pos': [2.573, 1.475, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [51, 29, 0]},
    {'t': 32.0, 'kind': 'pose', 'pos': [2.303, 1.475, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [46, 29, 0]},
    {'t': 33.0, 'kind': 'pose', 'pos': [2.003, 1.475, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [40, 29, 0]},
    {'t': 34.0, 'kind': 'pose', 'pos': [1.703, 1.475, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [34, 29, 0]},
    {'t': 35.0, 'kind': 'pose', 'pos': [1.475, 1.475, 0.075], 'state': 'arrived', 'level': 'ground', 'cell': [29, 29, 0]},
    {'t': 36.0, 'kind': 'pose', 'pos': [1.475, 1.175, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [29, 23, 0]},
    {'t': 37.0, 'kind': 'pose', 'pos': [1.39, 0.94, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [27, 18, 0]},
    {'t': 38.0, 'kind': 'pose', 'pos': [1.225, 0.805, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [24, 16, 0]},
    {'t': 39.0, 'kind': 'pose', 'pos': [1.165, 1.022, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [23, 20, 0]},
    {'t': 40.0, 'kind': 'pose', 'pos': [0.98, 1.219, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [19, 24, 0]},
    {'t': 41.0, 'kind': 'pose', 'pos': [1.148, 1.266, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [22, 25, 0]},
    {'t': 42.0, 'kind': 'pose', 'pos': [1.448, 1.272, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [28, 25, 0]},
    {'t': 43.0, 'kind': 'pose', 'pos': [1.715, 1.275, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [34, 25, 0]},
    {'t': 44.0, 'kind': 'pose', 'pos': [2.015, 1.275, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [40, 25, 0]},
    {'t': 45.0, 'kind': 'pose', 'pos': [2.315, 1.275, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [46, 25, 0]},
    {'t': 46.0, 'kind': 'pose', 'pos': [2.585, 1.275, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [51, 25, 0]},
    {'t': 47.0, 'kind': 'pose', 'pos': [2.875, 1.275, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [57, 25, 0]},
    {'t': 48.0, 'kind': 'pose', 'pos': [3.074, 1.172, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [61, 23, 0]},
    {'t': 49.0, 'kind': 'pose', 'pos': [3.267, 0.983, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [65, 19, 0]},
    {'t': 50.0, 'kind': 'pose', 'pos': [3.475, 0.975, 0.075], 'state': 'arrived', 'level': 'ground', 'cell': [69, 19, 0]},
    {'t': 51.0, 'kind': 'pose', 'pos': [3.709, 0.788, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [74, 15, 0]},
    {'t': 52.0, 'kind': 'pose', 'pos': [3.775, 0.625, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [75, 12, 0]},
    {'t': 53.0, 'kind': 'pose', 'pos': [3.661, 0.461, 0.075], 'state': 'moving', 'level': 'ground', 'cell': [73, 9, 0]},
    {'t': 54.0, 'kind': 'pose', 'pos': [3.483, 0.333, 0.07], 'state': 'moving', 'level': 'ground', 'cell': [69, 6, 0]},
    {'t': 55.0, 'kind': 'pose', 'pos': [3.213, 0.331, -0.011], 'state': 'moving', 'level': 'ramp', 'cell': [64, 6, -2]},
    {'t': 56.0, 'kind': 'pose', 'pos': [2.913, 0.328, -0.101], 'state': 'moving', 'level': 'ramp', 'cell': [58, 6, -4]},
    {'t': 57.0, 'kind': 'pose', 'pos': [2.613, 0.326, -0.191], 'state': 'moving', 'level': 'ramp', 'cell': [52, 6, -5]},
    {'t': 58.0, 'kind': 'pose', 'pos': [2.387, 0.431, -0.259], 'state': 'moving', 'level': 'ramp', 'cell': [47, 8, -7]},
    {'t': 59.0, 'kind': 'pose', 'pos': [2.36, 0.405, -0.267], 'state': 'moving', 'level': 'ramp', 'cell': [47, 8, -7]},
    {'t': 60.0, 'kind': 'pose', 'pos': [2.275, 0.225, -0.292], 'state': 'moving', 'level': 'ramp', 'cell': [45, 4, -7]},
    {'t': 61.0, 'kind': 'pose', 'pos': [2.105, 0.395, -0.343], 'state': 'moving', 'level': 'ramp', 'cell': [42, 7, -8]},
    {'t': 62.0, 'kind': 'pose', 'pos': [2.075, 0.325, -0.352], 'state': 'arrived', 'level': 'ramp', 'cell': [41, 6, -9]},
    {'t': 63.0, 'kind': 'pose', 'pos': [1.975, 0.375, -0.382], 'state': 'moving', 'level': 'ramp', 'cell': [39, 7, -9]},
    {'t': 64.0, 'kind': 'pose', 'pos': [1.833, 0.317, -0.425], 'state': 'arrived', 'level': 'ramp', 'cell': [36, 6, -10]},
    {'t': 65.0, 'kind': 'pose', 'pos': [1.598, 0.402, -0.496], 'state': 'moving', 'level': 'ramp', 'cell': [31, 8, -11]},
    {'t': 66.0, 'kind': 'pose', 'pos': [1.531, 0.373, -0.516], 'state': 'moving', 'level': 'B1', 'cell': [30, 7, -12]},
    {'t': 67.0, 'kind': 'pose', 'pos': [1.489, 0.415, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [29, 8, -12]},
    {'t': 68.0, 'kind': 'pose', 'pos': [1.378, 0.403, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [27, 8, -12]},
    {'t': 69.0, 'kind': 'pose', 'pos': [1.227, 0.573, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [24, 11, -12]},
    {'t': 70.0, 'kind': 'pose', 'pos': [1.209, 0.689, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [24, 13, -12]},
    {'t': 71.0, 'kind': 'pose', 'pos': [1.367, 0.817, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [27, 16, -12]},
    {'t': 72.0, 'kind': 'pose', 'pos': [1.374, 0.885, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [27, 17, -12]},
    {'t': 73.0, 'kind': 'pose', 'pos': [1.548, 0.958, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [30, 19, -12]},
    {'t': 74.0, 'kind': 'pose', 'pos': [1.581, 1.149, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [31, 22, -12]},
    {'t': 75.0, 'kind': 'pose', 'pos': [1.411, 1.319, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [28, 26, -12]},
    {'t': 76.0, 'kind': 'pose', 'pos': [1.22, 1.51, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [24, 30, -12]},
    {'t': 77.0, 'kind': 'pose', 'pos': [1.033, 1.637, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [20, 32, -12]},
    {'t': 78.0, 'kind': 'pose', 'pos': [0.793, 1.637, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [15, 32, -12]},
    {'t': 79.0, 'kind': 'pose', 'pos': [0.806, 1.471, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [16, 29, -12]},
    {'t': 80.0, 'kind': 'pose', 'pos': [0.616, 1.395, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [12, 27, -12]},
    {'t': 81.0, 'kind': 'pose', 'pos': [0.42, 1.58, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [8, 31, -12]},
    {'t': 82.0, 'kind': 'pose', 'pos': [0.39, 1.58, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [7, 31, -12]},
    {'t': 83.0, 'kind': 'pose', 'pos': [0.164, 1.686, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [3, 33, -12]},
    {'t': 84.0, 'kind': 'pose', 'pos': [0.333, 1.517, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [6, 30, -12]},
    {'t': 85.0, 'kind': 'pose', 'pos': [0.535, 1.375, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [10, 27, -12]},
    {'t': 86.0, 'kind': 'pose', 'pos': [0.78, 1.437, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [15, 28, -12]},
    {'t': 87.0, 'kind': 'pose', 'pos': [0.974, 1.625, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [19, 32, -12]},
    {'t': 88.0, 'kind': 'pose', 'pos': [1.022, 1.837, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [20, 36, -12]},
    {'t': 89.0, 'kind': 'pose', 'pos': [1.205, 1.925, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [24, 38, -12]},
    {'t': 90.0, 'kind': 'pose', 'pos': [1.505, 1.925, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [30, 38, -12]},
    {'t': 91.0, 'kind': 'pose', 'pos': [1.775, 1.925, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [35, 38, -12]},
    {'t': 92.0, 'kind': 'pose', 'pos': [2.075, 1.925, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [41, 38, -12]},
    {'t': 93.0, 'kind': 'pose', 'pos': [2.295, 1.903, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [45, 38, -12]},
    {'t': 94.0, 'kind': 'pose', 'pos': [2.225, 1.695, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [44, 33, -12]},
    {'t': 95.0, 'kind': 'pose', 'pos': [2.373, 1.527, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [47, 30, -12]},
    {'t': 96.0, 'kind': 'pose', 'pos': [2.587, 1.481, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [51, 29, -12]},
    {'t': 97.0, 'kind': 'pose', 'pos': [2.887, 1.476, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [57, 29, -12]},
    {'t': 98.0, 'kind': 'pose', 'pos': [3.069, 1.33, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [61, 26, -12]},
    {'t': 99.0, 'kind': 'pose', 'pos': [3.26, 1.139, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [65, 22, -12]},
    {'t': 100.0, 'kind': 'pose', 'pos': [3.239, 0.926, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [64, 18, -12]},
    {'t': 101.0, 'kind': 'pose', 'pos': [3.175, 0.975, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [63, 19, -12]},
    {'t': 102.0, 'kind': 'pose', 'pos': [3.397, 1.025, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [67, 20, -12]},
    {'t': 103.0, 'kind': 'pose', 'pos': [3.595, 0.855, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [71, 17, -12]},
    {'t': 104.0, 'kind': 'pose', 'pos': [3.775, 0.675, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [75, 13, -12]},
    {'t': 105.0, 'kind': 'pose', 'pos': [3.725, 0.525, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [74, 10, -12]},
    {'t': 106.0, 'kind': 'pose', 'pos': [3.796, 0.604, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [75, 12, -12]},
    {'t': 107.0, 'kind': 'pose', 'pos': [3.832, 0.434, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [76, 8, -12]},
    {'t': 108.0, 'kind': 'pose', 'pos': [3.675, 0.375, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [73, 7, -12]},
    {'t': 109.0, 'kind': 'pose', 'pos': [3.574, 0.391, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [71, 7, -12]},
    {'t': 110.0, 'kind': 'pose', 'pos': [3.395, 0.325, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [67, 6, -12]},
    {'t': 111.0, 'kind': 'pose', 'pos': [3.225, 0.427, -0.525], 'state': 'blocked', 'level': 'B1', 'cell': [64, 8, -12]},
    {'t': 112.0, 'kind': 'pose', 'pos': [3.154, 0.296, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [63, 5, -12]},
    {'t': 113.0, 'kind': 'pose', 'pos': [3.069, 0.381, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [61, 7, -12]},
    {'t': 114.0, 'kind': 'pose', 'pos': [2.829, 0.381, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [56, 7, -12]},
    {'t': 115.0, 'kind': 'pose', 'pos': [2.642, 0.296, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [52, 5, -12]},
    {'t': 116.0, 'kind': 'pose', 'pos': [2.625, 0.375, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [52, 7, -12]},
    {'t': 117.0, 'kind': 'pose', 'pos': [2.781, 0.269, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [55, 5, -12]},
    {'t': 118.0, 'kind': 'pose', 'pos': [3.051, 0.27, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [61, 5, -12]},
    {'t': 119.0, 'kind': 'pose', 'pos': [3.351, 0.271, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [67, 5, -12]},
    {'t': 120.0, 'kind': 'pose', 'pos': [3.651, 0.273, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [73, 5, -12]},
    {'t': 121.0, 'kind': 'pose', 'pos': [3.921, 0.275, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [78, 5, -12]},
    {'t': 122.0, 'kind': 'pose', 'pos': [3.775, 0.485, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [75, 9, -12]},
    {'t': 123.0, 'kind': 'pose', 'pos': [3.737, 0.711, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [74, 14, -12]},
    {'t': 124.0, 'kind': 'pose', 'pos': [3.579, 0.921, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [71, 18, -12]},
    {'t': 125.0, 'kind': 'pose', 'pos': [3.385, 0.966, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [67, 19, -12]},
    {'t': 126.0, 'kind': 'pose', 'pos': [3.193, 1.024, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [63, 20, -12]},
    {'t': 127.0, 'kind': 'pose', 'pos': [2.99, 1.11, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [59, 22, -12]},
    {'t': 128.0, 'kind': 'pose', 'pos': [2.799, 1.301, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [55, 26, -12]},
    {'t': 129.0, 'kind': 'pose', 'pos': [2.63, 1.47, -0.525], 'state': 'arrived', 'level': 'B1', 'cell': [52, 29, -12]},
    {'t': 130.0, 'kind': 'pose', 'pos': [2.383, 1.517, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [47, 30, -12]},
    {'t': 131.0, 'kind': 'pose', 'pos': [2.229, 1.726, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [44, 34, -12]},
    {'t': 132.0, 'kind': 'pose', 'pos': [2.267, 1.917, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [45, 38, -12]},
    {'t': 133.0, 'kind': 'pose', 'pos': [2.446, 2.046, -0.525], 'state': 'moving', 'level': 'B1', 'cell': [48, 40, -12]},
    {'t': 134.0, 'kind': 'pose', 'pos': [2.707, 2.069, -0.587], 'state': 'moving', 'level': 'ramp', 'cell': [54, 41, -13]},
    {'t': 135.0, 'kind': 'pose', 'pos': [3.007, 2.071, -0.677], 'state': 'moving', 'level': 'ramp', 'cell': [60, 41, -15]},
    {'t': 136.0, 'kind': 'pose', 'pos': [3.307, 2.074, -0.767], 'state': 'moving', 'level': 'ramp', 'cell': [66, 41, -17]},
    {'t': 137.0, 'kind': 'pose', 'pos': [3.542, 1.99, -0.838], 'state': 'moving', 'level': 'ramp', 'cell': [70, 39, -18]},
    {'t': 138.0, 'kind': 'pose', 'pos': [3.712, 2.117, -0.889], 'state': 'moving', 'level': 'ramp', 'cell': [74, 42, -19]},
    {'t': 139.0, 'kind': 'pose', 'pos': [3.776, 2.031, -0.908], 'state': 'arrived', 'level': 'ramp', 'cell': [75, 40, -20]},
    {'t': 140.0, 'kind': 'pose', 'pos': [3.675, 1.975, -0.877], 'state': 'moving', 'level': 'ramp', 'cell': [73, 39, -19]},
    {'t': 141.0, 'kind': 'pose', 'pos': [3.865, 2.075, -0.934], 'state': 'moving', 'level': 'ramp', 'cell': [77, 41, -20]},
    {'t': 142.0, 'kind': 'pose', 'pos': [4.165, 2.075, -1.024], 'state': 'moving', 'level': 'ramp', 'cell': [83, 41, -22]},
    {'t': 143.0, 'kind': 'pose', 'pos': [4.465, 2.075, -1.114], 'state': 'moving', 'level': 'B2', 'cell': [89, 41, -24]},
    {'t': 144.0, 'kind': 'pose', 'pos': [4.652, 1.99, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [93, 39, -24]},
    {'t': 145.0, 'kind': 'pose', 'pos': [4.587, 2.075, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [91, 41, -24]},
    {'t': 146.0, 'kind': 'pose', 'pos': [4.317, 2.075, -1.07], 'state': 'moving', 'level': 'ramp', 'cell': [86, 41, -23]},
    {'t': 147.0, 'kind': 'pose', 'pos': [4.095, 2.117, -1.003], 'state': 'moving', 'level': 'ramp', 'cell': [81, 42, -22]},
    {'t': 148.0, 'kind': 'pose', 'pos': [4.065, 2.046, -0.994], 'state': 'moving', 'level': 'ramp', 'cell': [81, 40, -21]},
    {'t': 149.0, 'kind': 'pose', 'pos': [4.225, 2.075, -1.042], 'state': 'arrived', 'level': 'ramp', 'cell': [84, 41, -22]},
    {'t': 150.0, 'kind': 'pose', 'pos': [4.485, 2.075, -1.12], 'state': 'moving', 'level': 'B2', 'cell': [89, 41, -24]},
    {'t': 151.0, 'kind': 'pose', 'pos': [4.689, 1.909, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [93, 38, -24]},
    {'t': 152.0, 'kind': 'pose', 'pos': [4.725, 1.665, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [94, 33, -24]},
    {'t': 153.0, 'kind': 'pose', 'pos': [4.581, 1.482, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [91, 29, -24]},
    {'t': 154.0, 'kind': 'pose', 'pos': [4.281, 1.48, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [85, 29, -24]},
    {'t': 155.0, 'kind': 'pose', 'pos': [3.981, 1.478, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [79, 29, -24]},
    {'t': 156.0, 'kind': 'pose', 'pos': [3.681, 1.476, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [73, 29, -24]},
    {'t': 157.0, 'kind': 'pose', 'pos': [3.411, 1.475, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [68, 29, -24]},
    {'t': 158.0, 'kind': 'pose', 'pos': [3.111, 1.475, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [62, 29, -24]},
    {'t': 159.0, 'kind': 'pose', 'pos': [2.811, 1.475, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [56, 29, -24]},
    {'t': 160.0, 'kind': 'pose', 'pos': [2.568, 1.411, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [51, 28, -24]},
    {'t': 161.0, 'kind': 'pose', 'pos': [2.372, 1.311, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [47, 26, -24]},
    {'t': 162.0, 'kind': 'pose', 'pos': [2.525, 1.425, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [50, 28, -24]},
    {'t': 163.0, 'kind': 'pose', 'pos': [2.383, 1.567, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [47, 31, -24]},
    {'t': 164.0, 'kind': 'pose', 'pos': [2.167, 1.514, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [43, 30, -24]},
    {'t': 165.0, 'kind': 'pose', 'pos': [1.998, 1.348, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [39, 26, -24]},
    {'t': 166.0, 'kind': 'pose', 'pos': [1.807, 1.369, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [36, 27, -24]},
    {'t': 167.0, 'kind': 'pose', 'pos': [1.567, 1.369, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [31, 27, -24]},
    {'t': 168.0, 'kind': 'pose', 'pos': [1.38, 1.454, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [27, 29, -24]},
    {'t': 169.0, 'kind': 'pose', 'pos': [1.189, 1.263, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [23, 25, -24]},
    {'t': 170.0, 'kind': 'pose', 'pos': [1.019, 1.093, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [20, 21, -24]},
    {'t': 171.0, 'kind': 'pose', 'pos': [0.775, 1.075, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [15, 21, -24]},
    {'t': 172.0, 'kind': 'pose', 'pos': [0.579, 0.969, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [11, 19, -24]},
    {'t': 173.0, 'kind': 'pose', 'pos': [0.339, 0.969, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [6, 19, -24]},
    {'t': 174.0, 'kind': 'pose', 'pos': [0.173, 1.075, -1.125], 'state': 'blocked', 'level': 'B2', 'cell': [3, 21, -24]},
    {'t': 175.0, 'kind': 'pose', 'pos': [0.36, 1.09, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [7, 21, -24]},
    {'t': 176.0, 'kind': 'pose', 'pos': [0.354, 0.904, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [7, 18, -24]},
    {'t': 177.0, 'kind': 'pose', 'pos': [0.163, 0.84, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [3, 16, -24]},
    {'t': 178.0, 'kind': 'pose', 'pos': [0.275, 0.822, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [5, 16, -24]},
    {'t': 179.0, 'kind': 'pose', 'pos': [0.225, 0.925, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [4, 18, -24]},
    {'t': 180.0, 'kind': 'pose', 'pos': [0.447, 0.875, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [8, 17, -24]},
    {'t': 181.0, 'kind': 'pose', 'pos': [0.623, 0.727, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [12, 14, -24]},
    {'t': 182.0, 'kind': 'pose', 'pos': [0.867, 0.683, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [17, 13, -24]},
    {'t': 183.0, 'kind': 'pose', 'pos': [0.996, 0.504, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [19, 10, -24]},
    {'t': 184.0, 'kind': 'pose', 'pos': [0.975, 0.325, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [19, 6, -24]},
    {'t': 185.0, 'kind': 'pose', 'pos': [0.804, 0.202, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [16, 4, -24]},
    {'t': 186.0, 'kind': 'pose', 'pos': [1.001, 0.314, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [20, 6, -24]},
    {'t': 187.0, 'kind': 'pose', 'pos': [1.125, 0.525, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [22, 10, -24]},
    {'t': 188.0, 'kind': 'pose', 'pos': [1.167, 0.717, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [23, 14, -24]},
    {'t': 189.0, 'kind': 'pose', 'pos': [1.38, 0.93, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [27, 18, -24]},
    {'t': 190.0, 'kind': 'pose', 'pos': [1.57, 1.12, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [31, 22, -24]},
    {'t': 191.0, 'kind': 'pose', 'pos': [1.761, 1.311, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [35, 26, -24]},
    {'t': 192.0, 'kind': 'pose', 'pos': [1.925, 1.475, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [38, 29, -24]},
    {'t': 193.0, 'kind': 'pose', 'pos': [2.146, 1.496, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [42, 29, -24]},
    {'t': 194.0, 'kind': 'pose', 'pos': [2.345, 1.575, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [46, 31, -24]},
    {'t': 195.0, 'kind': 'pose', 'pos': [2.552, 1.448, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [51, 28, -24]},
    {'t': 196.0, 'kind': 'pose', 'pos': [2.764, 1.236, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [55, 24, -24]},
    {'t': 197.0, 'kind': 'pose', 'pos': [3.034, 1.23, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [60, 24, -24]},
    {'t': 198.0, 'kind': 'pose', 'pos': [3.325, 1.225, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [66, 24, -24]},
    {'t': 199.0, 'kind': 'pose', 'pos': [3.595, 1.225, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [71, 24, -24]},
    {'t': 200.0, 'kind': 'pose', 'pos': [3.865, 1.225, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [77, 24, -24]},
    {'t': 201.0, 'kind': 'pose', 'pos': [4.087, 1.204, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [81, 24, -24]},
    {'t': 202.0, 'kind': 'pose', 'pos': [4.282, 1.018, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [85, 20, -24]},
    {'t': 203.0, 'kind': 'pose', 'pos': [4.517, 0.927, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [90, 18, -24]},
    {'t': 204.0, 'kind': 'pose', 'pos': [4.723, 0.777, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [94, 15, -24]},
    {'t': 205.0, 'kind': 'pose', 'pos': [4.725, 0.537, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [94, 10, -24]},
    {'t': 206.0, 'kind': 'pose', 'pos': [4.525, 0.375, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [90, 7, -24]},
    {'t': 207.0, 'kind': 'pose', 'pos': [4.303, 0.331, -1.184], 'state': 'moving', 'level': 'ramp', 'cell': [86, 6, -25]},
    {'t': 208.0, 'kind': 'pose', 'pos': [4.003, 0.329, -1.274], 'state': 'moving', 'level': 'ramp', 'cell': [80, 6, -27]},
    {'t': 209.0, 'kind': 'pose', 'pos': [3.703, 0.327, -1.364], 'state': 'moving', 'level': 'ramp', 'cell': [74, 6, -29]},
    {'t': 210.0, 'kind': 'pose', 'pos': [3.45, 0.368, -1.44], 'state': 'moving', 'level': 'ramp', 'cell': [69, 7, -30]},
    {'t': 211.0, 'kind': 'pose', 'pos': [3.354, 0.396, -1.469], 'state': 'moving', 'level': 'ramp', 'cell': [67, 7, -31]},
    {'t': 212.0, 'kind': 'pose', 'pos': [3.41, 0.3, -1.452], 'state': 'moving', 'level': 'ramp', 'cell': [68, 6, -31]},
    {'t': 213.0, 'kind': 'pose', 'pos': [3.238, 0.272, -1.504], 'state': 'moving', 'level': 'ramp', 'cell': [64, 5, -32]},
    {'t': 214.0, 'kind': 'pose', 'pos': [3.069, 0.431, -1.554], 'state': 'arrived', 'level': 'ramp', 'cell': [61, 8, -33]},
    {'t': 215.0, 'kind': 'pose', 'pos': [2.92, 0.367, -1.599], 'state': 'moving', 'level': 'ramp', 'cell': [58, 7, -33]},
    {'t': 216.0, 'kind': 'pose', 'pos': [2.751, 0.325, -1.65], 'state': 'arrived', 'level': 'ramp', 'cell': [55, 6, -34]},
    {'t': 217.0, 'kind': 'pose', 'pos': [2.56, 0.304, -1.707], 'state': 'moving', 'level': 'B3', 'cell': [51, 6, -36]},
    {'t': 218.0, 'kind': 'pose', 'pos': [2.39, 0.389, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [47, 7, -36]},
    {'t': 219.0, 'kind': 'pose', 'pos': [2.22, 0.431, -1.725], 'state': 'arrived', 'level': 'B3', 'cell': [44, 8, -36]},
    {'t': 220.0, 'kind': 'pose', 'pos': [1.986, 0.346, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [39, 6, -36]},
    {'t': 221.0, 'kind': 'pose', 'pos': [1.816, 0.261, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [36, 5, -36]},
    {'t': 222.0, 'kind': 'pose', 'pos': [1.572, 0.325, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [31, 6, -36]},
    {'t': 223.0, 'kind': 'pose', 'pos': [1.302, 0.325, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [26, 6, -36]},
    {'t': 224.0, 'kind': 'pose', 'pos': [1.002, 0.325, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 6, -36]},
    {'t': 225.0, 'kind': 'pose', 'pos': [0.827, 0.473, -1.725], 'state': 'arrived', 'level': 'B3', 'cell': [16, 9, -36]},
    {'t': 226.0, 'kind': 'pose', 'pos': [0.678, 0.652, -1.725], 'state': 'blocked', 'level': 'B3', 'cell': [13, 13, -36]},
    {'t': 227.0, 'kind': 'pose', 'pos': [0.875, 0.625, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [17, 12, -36]},
    {'t': 228.0, 'kind': 'pose', 'pos': [1.024, 0.803, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 16, -36]},
    {'t': 229.0, 'kind': 'pose', 'pos': [1.024, 1.103, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 22, -36]},
    {'t': 230.0, 'kind': 'pose', 'pos': [0.984, 1.357, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [19, 27, -36]},
]


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def pose_problems(records):
    """[(t or index, problem)] for every pose that is not finite and well formed; [] if all are."""
    out, last = [], -math.inf
    for n, r in enumerate(r for r in records if r.get("kind") == "pose"):
        where = r.get("t", f"#{n}")
        t, pos, cell = r.get("t"), r.get("pos"), r.get("cell")
        if not _finite(t) or t < 0:
            out.append((where, f"t {t!r}"))
            continue
        if t < last:
            out.append((where, f"t goes back from {last}"))
        last = t
        if not (isinstance(pos, list) and len(pos) == 3 and all(_finite(v) for v in pos)):
            out.append((where, f"pos {pos!r}"))
            continue
        if not all(lo <= v <= hi for v, (lo, hi) in zip(pos, BOUNDS, strict=True)):
            out.append((where, f"pos {pos} outside the building"))
        if not (isinstance(cell, list) and len(cell) == 3 and all(isinstance(c, int) and not isinstance(c, bool) for c in cell)):
            out.append((where, f"cell {cell!r}"))
        else:
            want = (pos[0] / RES, pos[1] / RES, (pos[2] - RIDE) / RES)
            if any(abs(c - w) > 1.0 + 1e-6 for c, w in zip(cell, want, strict=True)):
                out.append((where, f"cell {cell} does not match pos {pos}"))
        if r.get("state") not in STATES:
            out.append((where, f"state {r.get('state')!r}"))
        if r.get("level") not in LEVELS:
            out.append((where, f"level {r.get('level')!r}"))
    return out


def test_real_b3_poses_are_finite_and_well_formed():
    assert len(REAL_B3_POSES) == 231
    assert pose_problems(REAL_B3_POSES) == []
    zs = [p["pos"][2] for p in REAL_B3_POSES]
    assert max(zs) == 0.675 and min(zs) == -1.725              # L1 down to B3, at ride height


@pytest.mark.parametrize("floor", ["b2", "b3"])
def test_full_real_logs(floor):
    env = os.environ.get(f"{floor.upper()}_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "runs").glob(f"{floor}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip(f"no full {floor.upper()} log")
    records = [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    poses = [r for r in records if r.get("kind") == "pose"]
    assert poses and pose_problems(records) == []
    print(f"{found[-1].name}: {len(poses)} poses ok")


def test_nan_and_infinity_from_a_real_file_are_caught(tmp_path):
    """python's json writes NaN/Infinity unquoted and reads them back as floats: the check must see them."""
    bad = [dict(REAL_B3_POSES[5], pos=[float("nan"), 1.0, 0.675]), dict(REAL_B3_POSES[6], t=float("inf"))]
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in bad) + "\n", encoding="utf-8")
    back = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    problems = pose_problems(back)
    assert [p[1].split()[0] for p in problems] == ["pos", "t"]


def _pose(**change):
    return [dict(REAL_B3_POSES[10], **change)]


@pytest.mark.parametrize("change,word", [
    ({"t": -1.0}, "t"),
    ({"t": None}, "t"),
    ({"pos": [1.0, 2.0]}, "pos"),
    ({"pos": [1.0, "2", 0.675]}, "pos"),
    ({"pos": [50.0, 1.0, 0.675]}, "pos"),               # outside the building
    ({"cell": [10, 15]}, "cell"),
    ({"cell": [10.0, 15, 12]}, "cell"),                 # not an int
    ({"cell": [99, 15, 12]}, "cell"),                   # does not match pos
    ({"state": "flying"}, "state"),
    ({"level": "B9"}, "level"),
])
def test_malformed_poses_are_caught(change, word):
    problems = pose_problems(_pose(**change))
    assert problems and problems[0][1].split()[0] == word, problems


def test_time_going_back_is_caught():
    a, b = REAL_B3_POSES[20], REAL_B3_POSES[21]
    assert [p[1] for p in pose_problems([b, a])] == [f"t goes back from {b['t']}"]
