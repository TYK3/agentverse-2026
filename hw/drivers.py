"""Driver stubs (Y10 part 2): each simulated sensor reads through the real chip's rate, latency and noise.

The sim computes ideal readings; a driver decides when a sample exists (the chip's rate), when the
computer sees it (latency), and what error it carries (noise, range limits). A real robot replaces
the stubs with real drivers that emit the same channel values, so everything downstream is the same.

Figures marked `source` come from docs/hardware.md and docs/electronics.md; figures marked
`assumed` are our stand-ins until measured on the part.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Spec:
    part: str
    rate_hz: float
    latency_s: float
    noise: float
    notes: dict[str, str] = field(default_factory=dict)  # figure -> "source: ..." or "assumed"


SPECS: dict[str, Spec] = {
    "lidar": Spec("EAI YDLIDAR T-mini Pro", rate_hz=10.0, latency_s=0.05, noise=0.01, notes={
        "rate_hz": "source: 6-12 Hz scan (T-mini Pro datasheet); 10 Hz chosen",
        "range": "source: 0.02-12 m",
        "latency_s": "assumed: half a revolution at 10 Hz",
        "noise": "assumed: 1% of range, 1 sigma"}),
    "thermal": Spec("Teledyne FLIR Lepton 3.5", rate_hz=8.7, latency_s=0.115, noise=0.01, notes={
        "rate_hz": "source: 8.7 Hz export-compliant (Lepton 3.5 datasheet)",
        "latency_s": "assumed: one frame period",
        "noise": "assumed: 0.01 of the 0..1 intensity scale, 1 sigma"}),
    "acoustic": Spec("Seeed ReSpeaker Mic Array v2.0 (XVF-3000 DOA)", rate_hz=10.0, latency_s=0.1, noise=5.0, notes={
        "rate_hz": "assumed: direction of arrival polled at 10 Hz over USB",
        "latency_s": "assumed: 100 ms analysis window",
        "noise": "assumed: 5 degrees bearing error, 1 sigma"}),
    "imu": Spec("CEVA BNO085", rate_hz=100.0, latency_s=0.005, noise=math.radians(0.5), notes={
        "rate_hz": "source: rotation vector up to 400 Hz; 100 Hz chosen",
        "latency_s": "assumed: 5 ms",
        "noise": "assumed: 0.5 degree heading error, 1 sigma"}),
    "odometry": Spec("AgileX LIMO Pro wheel odometry", rate_hz=20.0, latency_s=0.02, noise=0.005, notes={
        "rate_hz": "assumed: 20 Hz chassis feedback",
        "noise": "assumed: 5 mm position error, 1 sigma"}),
    "camera": Spec("Orbbec DaBai (in the LIMO Pro)", rate_hz=10.0, latency_s=0.07, noise=0.0, notes={
        "rate_hz": "assumed: 10 Hz stream for mapping (the sim renders one frame per tick)",
        "latency_s": "assumed: 70 ms capture and JPEG encode"}),
}

LIDAR_MIN, LIDAR_MAX = 0.02, 12.0  # T-mini Pro range (source)


class Driver:
    """One sensor channel: sample at the chip's rate, hold each sample for its latency, add noise."""

    def __init__(self, channel: str, spec: Spec | None = None, rng: np.random.Generator | None = None):
        self.channel = channel
        self.spec = spec or SPECS[channel]
        self.rng = rng or np.random.default_rng(0)
        self.next_sample = 0.0
        self._queue: list[tuple[float, int, Any]] = []  # (release time, seq, value)
        self._seq = 0
        self.latest: Any = None
        self.latest_t: float | None = None

    def offer(self, t: float, ideal: Any) -> bool:
        """The sim's ideal reading at time t. Returns True if the chip took a sample now."""
        if ideal is None or t + 1e-9 < self.next_sample:
            return False
        period = 1.0 / self.spec.rate_hz
        # keep a steady clock; skip missed periods instead of bursting
        self.next_sample = max(self.next_sample + period, t + period - 1e-9) if self.next_sample else t + period
        self._seq += 1
        heapq.heappush(self._queue, (t + self.spec.latency_s, self._seq, self.measure(ideal)))
        return True

    def poll(self, t: float) -> bool:
        """Release samples whose latency has passed. Returns True if `latest` changed."""
        changed = False
        while self._queue and self._queue[0][0] <= t + 1e-9:
            release, _, value = heapq.heappop(self._queue)
            self.latest, self.latest_t, changed = value, release, True
        return changed

    def measure(self, ideal: Any) -> Any:
        return ideal


class LidarDriver(Driver):
    """Ranges with T-mini Pro noise. A miss stays a miss: it reads `miss_at`, the value the sim and the
    map builder use for "no return" (sim/sensors.py MAX_RANGE), so maps from either source agree."""

    def __init__(self, rng=None, miss_at=6.0):
        super().__init__("lidar", rng=rng)
        self.miss_at = miss_at

    def measure(self, ideal):
        r = np.asarray(ideal, float)
        noisy = np.clip(r + self.rng.normal(0.0, self.spec.noise, r.shape) * r, LIDAR_MIN, LIDAR_MAX)
        lost = (r < LIDAR_MIN) | (r >= self.miss_at - 1e-9)  # too close to measure, or no return
        noisy = np.where(lost, self.miss_at, np.minimum(noisy, self.miss_at))
        return [round(float(v), 3) for v in noisy]


class ThermalDriver(Driver):
    def __init__(self, rng=None):
        super().__init__("thermal", rng=rng)

    def measure(self, ideal):
        g = np.asarray(ideal, float)
        return np.round(np.clip(g + self.rng.normal(0.0, self.spec.noise, g.shape), 0.0, 1.0), 2).tolist()


class AcousticDriver(Driver):
    def __init__(self, rng=None):
        super().__init__("acoustic", rng=rng)

    def measure(self, ideal):
        out = dict(ideal)
        if out.get("level", 0) > 0:
            bearing = out["bearing"] + self.rng.normal(0.0, self.spec.noise)
            b = round(float((bearing + 180.0) % 360.0 - 180.0), 1)
            out["bearing"] = b - 360.0 if b >= 180.0 else b  # rounding can land on +180
        return out


class ImuDriver(Driver):
    def __init__(self, rng=None):
        super().__init__("imu", rng=rng)

    def measure(self, ideal):
        yaw = float(ideal) + self.rng.normal(0.0, self.spec.noise)
        return round(math.atan2(math.sin(yaw), math.cos(yaw)), 3)


class OdometryDriver(Driver):
    def __init__(self, rng=None):
        super().__init__("odometry", rng=rng)

    def measure(self, ideal):
        p = np.asarray(ideal, float)
        p = p + np.array([*self.rng.normal(0.0, self.spec.noise, 2), 0.0])
        return [round(float(v), 3) for v in p]


class ScoutHardware:
    """The Scout's sensor stack as the computer sees it: sim readings in, sensors/scout frames out."""

    def __init__(self, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.drivers: dict[str, Driver] = {
            "lidar": LidarDriver(rng), "thermal": ThermalDriver(rng), "acoustic": AcousticDriver(rng),
            "imu": ImuDriver(rng), "odometry": OdometryDriver(rng), "camera": Driver("camera", rng=rng),
        }
        self.motion = None

    def step(self, ideal: dict[str, Any]) -> dict[str, Any] | None:
        """Feed one ideal sensors/scout payload (from sim/world.py). Returns a frame once every
        channel has delivered at least one sample, else None. Stale channels keep their last value,
        as a real driver stack would."""
        t = float(ideal.get("t", 0.0))
        pose = ideal["pose"]
        feeds = {"lidar": ideal.get("lidar"), "thermal": ideal.get("thermal"),
                 "acoustic": ideal.get("acoustic"), "imu": pose["yaw"], "odometry": pose["pos"],
                 "camera": ideal.get("camera")}
        for name, drv in self.drivers.items():
            drv.offer(t, feeds[name])
            drv.poll(t)
        self.motion = ideal.get("motion", self.motion)
        need = ("lidar", "thermal", "acoustic", "imu", "odometry")
        if any(self.drivers[n].latest is None for n in need):
            return None
        frame = {
            "t": round(t, 2),
            "pose": {"pos": self.drivers["odometry"].latest, "yaw": self.drivers["imu"].latest},
            "lidar": self.drivers["lidar"].latest,
            "thermal": self.drivers["thermal"].latest,
            "acoustic": self.drivers["acoustic"].latest,
        }
        if self.motion is not None:
            frame["motion"] = self.motion
        if self.drivers["camera"].latest is not None:
            frame["camera"] = self.drivers["camera"].latest
        return frame

    def table(self) -> list[dict[str, Any]]:
        """Each channel's part, rate, latency and noise, and where each figure comes from."""
        return [{"channel": n, "part": d.spec.part, "rate_hz": d.spec.rate_hz, "latency_s": d.spec.latency_s,
                 "noise": d.spec.noise, "notes": d.spec.notes} for n, d in self.drivers.items()]
