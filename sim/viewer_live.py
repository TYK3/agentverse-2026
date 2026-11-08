"""Opt-in live MuJoCo window for a hub run (``SIM_VIEWER=1``).

The sim loop does not open a window until one line is added in
``sim/__init__.py``. With the other sim imports::

    from sim import viewer_live

In ``start()``, immediately after ``world.recorder = recorder.attach(world, bus)``::

    world.viewer = viewer_live.attach(world)

That is the whole hook. ``run()`` already calls ``world.tick``; ``attach``
wraps that tick. Leave ``SIM_VIEWER`` unset and the line returns ``None``
at once: no thread, no ``mujoco.viewer`` import, and the world is not read.
Set it to ``1`` and a passive viewer opens on a background thread. Only the
string ``1`` turns it on.

Each tick copies the live pose and returns. Drawing stays on the viewer
thread, so the hub's asyncio loop does not wait on GLFW and does not sleep
for the window. The copy is the joint state (``qpos``, ``qvel``), mocap
(Scout, Responder and the shaking ground) and equality flags. The viewer
keeps the sim's ``MjModel`` and a private ``MjData``. ``mj_kinematics`` on
that private copy places the geoms. The live ``MjData`` is only read.

The viewer never calls ``mj_step``, never writes the live ``MjData``, and
never publishes. Closing the window stops its thread and leaves the physics
running. ``close`` also runs from ``atexit`` when the process exits. To drop
the window as soon as the sim task is cancelled, rather than when the
process exits, wrap ``run``::

    try:
        while True:
            ...
    finally:
        viewer_live.close(getattr(world, "viewer", None))

``sync(viewer)`` is the same hand-off the tick wrapper uses. Call it from a
loop that does not go through ``world.tick``. ``sync(None)`` and
``close(None)`` return immediately.

On Linux with neither ``DISPLAY`` nor ``WAYLAND_DISPLAY``, GLFW would abort
the process, so the viewer is not started and one warning is logged. If the
launch raises, another warning is logged and the run carries on. A bad
display that still aborts inside GLFW cannot be caught; that is MuJoCo's
own behaviour and is why the display is checked first.
"""

import atexit
import logging
import os
import sys
import threading

import mujoco
import numpy as np

log = logging.getLogger("sim.viewer")

CLOSE_TIMEOUT_S = 2.0


def enabled():
    """True only when ``SIM_VIEWER`` is the string ``1``."""
    return os.environ.get("SIM_VIEWER") == "1"


def display_available():
    """True when a passive GLFW window can be tried.

    On Linux, MuJoCo's viewer aborts the process if GLFW starts with no
    display, so this is checked before ``mujoco.viewer`` is imported. Other
    platforms try the launch and log a warning if it raises.
    """
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def launch_passive(model, data):
    """Open MuJoCo's passive viewer. Tests replace this."""
    import mujoco.viewer

    return mujoco.viewer.launch_passive(model, data)


def attach(world):
    """Start the live window, or return ``None`` when it stays off.

    When it starts, ``world.viewer`` is this handle and ``world.tick`` copies
    the pose out after each step. ``None`` means ``SIM_VIEWER`` is not ``1``,
    or there is no display (one warning). A launch that fails still returns
    the handle: ``sync`` and ``close`` are then no-ops and the tick still runs.
    """
    if not enabled():
        return None
    if not display_available():
        log.warning(
            "SIM_VIEWER=1 but no display is available; continuing without a live window"
        )
        return None
    try:
        viewer = LiveViewer(world.m, world.d)
    except Exception as exc:  # noqa: BLE001  (a bad model must not stop the hub)
        log.warning(
            "SIM_VIEWER=1 but the live viewer could not start (%s: %s); "
            "continuing without a live window",
            type(exc).__name__,
            exc,
        )
        return None
    world.viewer = viewer
    _follow_tick(world, viewer)
    viewer.start()
    return viewer


def sync(viewer):
    """Copy the live pose to ``viewer`` and return. ``None`` does nothing."""
    if viewer is not None:
        viewer.sync()


def close(viewer):
    """Close ``viewer`` and join its thread. ``None`` and a second call are safe."""
    if viewer is not None:
        viewer.close()


def _follow_tick(world, viewer):
    """After each ``world.tick``, hand the pose to the viewer and return the events."""
    tick = getattr(world, "tick", None)
    if not callable(tick):
        return

    def tick_and_show(*args, **kwargs):
        events = tick(*args, **kwargs)
        viewer.sync()
        return events

    world.tick = tick_and_show


def _is_running(handle):
    try:
        return bool(handle.is_running())
    except Exception:  # noqa: BLE001  (a dead window must not stop the hub)
        log.warning("SIM_VIEWER could not read the window state", exc_info=False)
        return False


class LiveViewer:
    """Passive window on a private copy of the sim pose.

    ``sync`` only fills a snapshot. The background thread copies that into
    its own ``MjData``, runs kinematics there, and calls ``handle.sync``.
    The asyncio loop never takes the viewer's lock and never draws.
    """

    def __init__(self, model, data):
        self.model = model
        self.data = data
        self._view = mujoco.MjData(model)
        if self._view is data:
            raise RuntimeError("refusing to point the viewer at the live MjData")
        self._qpos = np.empty_like(data.qpos)
        self._qvel = np.empty_like(data.qvel)
        self._mocap_pos = np.empty_like(data.mocap_pos)
        self._mocap_quat = np.empty_like(data.mocap_quat)
        self._eq_active = np.empty_like(data.eq_active)
        self._time = 0.0
        self._have = False
        self._warned = False
        self._lock = threading.Lock()
        self._handle_lock = threading.Lock()
        self._handle = None
        self._wake = threading.Event()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._failed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sim-viewer", daemon=True)

    def start(self):
        self._capture()
        atexit.register(self.close)
        self._thread.start()
        return self

    @property
    def running(self):
        """True while the window is open. False before launch and after it closes."""
        if self._stop.is_set() or self._failed.is_set():
            return False
        with self._handle_lock:
            handle = self._handle
        return handle is not None and _is_running(handle)

    def wait(self, timeout=CLOSE_TIMEOUT_S):
        """Block until the window is up or has failed. The hub loop must not call this."""
        if not self._ready.wait(timeout):
            return False
        return bool(self.running)

    def sync(self):
        """Snapshot the live pose and wake the viewer thread. Returns immediately."""
        if self._stop.is_set() or self._failed.is_set():
            return
        try:
            self._capture()
        except Exception as exc:  # noqa: BLE001  (a read of the pose must not stop the tick)
            if not self._warned:
                self._warned = True
                log.warning("SIM_VIEWER could not read the sim state (%s)", type(exc).__name__)
            return
        self._wake.set()

    def close(self):
        """Ask the window to exit and wait briefly for its thread."""
        self._stop.set()
        self._wake.set()
        self._close_handle()
        thread = self._thread
        if threading.current_thread() is not thread and thread.is_alive():
            thread.join(timeout=CLOSE_TIMEOUT_S)
            if thread.is_alive():
                log.warning("SIM_VIEWER window did not close within %ss", CLOSE_TIMEOUT_S)
        atexit.unregister(self.close)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _capture(self):
        data = self.data
        with self._lock:
            self._qpos[:] = data.qpos
            self._qvel[:] = data.qvel
            if self._mocap_pos.size:
                self._mocap_pos[:] = data.mocap_pos
                self._mocap_quat[:] = data.mocap_quat
            if self._eq_active.size:
                self._eq_active[:] = data.eq_active
            self._time = float(data.time)
            self._have = True

    def _apply(self):
        """Copy the snapshot into the private ``MjData`` and place the geoms there."""
        view = self._view
        if view is None or view is self.data:
            return False
        with self._lock:
            if not self._have:
                return False
            view.time = self._time
            view.qpos[:] = self._qpos
            view.qvel[:] = self._qvel
            if self._mocap_pos.size:
                view.mocap_pos[:] = self._mocap_pos
                view.mocap_quat[:] = self._mocap_quat
            if self._eq_active.size:
                view.eq_active[:] = self._eq_active
            self._have = False
        mujoco.mj_kinematics(self.model, view)
        return True

    def _run(self):
        handle = None
        try:
            self._apply()
            handle = launch_passive(self.model, self._view)
            self._apply()
            with self._handle_lock:
                self._handle = handle
            if self._stop.is_set():
                return
            self._ready.set()
            self._pump(handle)
        except Exception as exc:  # noqa: BLE001  (GLFW and the viewer fail in many ways)
            self._failed.set()
            log.warning(
                "SIM_VIEWER=1 but the live viewer could not start (%s: %s); "
                "continuing without a live window",
                type(exc).__name__,
                exc,
            )
        finally:
            self._ready.set()
            self.close()

    def _pump(self, handle):
        if self._stop.is_set() or not _is_running(handle):
            return
        self._draw(handle)
        while not self._stop.is_set() and _is_running(handle):
            if self._apply():
                self._draw(handle)
            if self._stop.is_set() or not _is_running(handle):
                break
            self._wake.wait(0.05)
            self._wake.clear()

    def _draw(self, handle):
        try:
            handle.sync()
        except Exception as exc:  # noqa: BLE001  (a draw error closes the window, not the sim)
            log.warning("SIM_VIEWER sync failed (%s); closing the live window", type(exc).__name__)
            self._stop.set()

    def _close_handle(self):
        with self._handle_lock:
            handle = self._handle
            self._handle = None
        if handle is None:
            return
        try:
            handle.close()
        except Exception as exc:  # noqa: BLE001  (closing a dead window must not raise)
            log.warning("SIM_VIEWER window did not close (%s)", type(exc).__name__)
