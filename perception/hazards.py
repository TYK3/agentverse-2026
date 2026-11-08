"""map/hazards from the Scout's own scans (Z1): cells at_risk or collapsed, always estimates.

Nothing here reads block poses. world/change only says that a shake (or an injected block) happened:
which blocks moved is sim truth, kept for scoring (perception/score.py).

  before a shake  at_risk where the pile stability from the depth points is low (perception/cloud.py:
                  overhangs above open floor and what carries them);
  at the shake    the grid freezes its cells (Grid.begin_change); the at_risk prediction stays up,
                  marked "not re-scanned yet", until the Scout sees those columns again;
  after it        the scan diff: cells that were free and now return hits have `appeared` (debris
                  landed): collapsed, with NEAR (0.15 m) around them at_risk. Cells that were occupied
                  and are now passed through have `cleared` (what stood there moved): at_risk.
                  Recent motion also lowers nearby pile stability (secondary falls).

Cells are plan cells on the ground layer k=0, like map/cells. Only at_risk and collapsed cells are
published; the planner replaces its list with each message, so a cell that drops out is clear.
"""

from perception.cloud import Cloud

NEAR = 3              # cells (0.15 m) around new debris that become at_risk
LAYERS = (0,)         # the ground layer, like map/cells
RANK = {"stable": 0, "at_risk": 1, "collapsed": 2}


def _ring(ij, r):
    i, j = ij
    return [(i + di, j + dj) for di in range(-r, r + 1) for dj in range(-r, r + 1)
            if (di or dj) and di * di + dj * dj <= r * r]


class Hazards:
    def __init__(self, grid, cloud=None):
        self.grid = grid
        self.cloud = cloud if cloud is not None else Cloud(grid.res)
        self.labels = {}          # (i, j) -> (status, why), rebuilt by update()
        self.collapsed = {}       # (i, j) -> why: debris seen landing, kept across shakes
        self.predicted = {}       # (i, j) -> why: at_risk at the last shake, until re-scanned
        self.change = ""          # "the aftershock at 12.3 s", for the reasons
        self.last = None          # the last message, to publish only changes

    def on_sensors(self, data):
        self.cloud.add_sensors(data)

    def on_change(self, data, t=None):
        """A shake (or an injected block) happened: freeze the map and diff what the Scout sees next."""
        t = self.grid.t if t is None else t
        self.update(t)
        self.predicted = {ij: why for ij, (s, why) in self.labels.items() if s == "at_risk"}
        self.grid.begin_change(t)
        self.cloud.reset()
        kind = "aftershock" if data.get("kind", "aftershock") == "aftershock" else "injected block"
        self.change = f"the {kind} at {t:.1f} s"

    def _rescanned(self, ij):
        """True once the Scout has measured column ij again since the last shake."""
        if any((ij[0], ij[1], k) in self.grid.after for k in self.grid.layers):
            return True
        return ij in self.cloud.columns

    def update(self, t):
        """Rebuild the labels from the scans; return the map/hazards message if it changed, else None."""
        labels = {}

        def mark(ij, status, why):
            cur = labels.get(ij)
            if cur is None or RANK[status] > RANK[cur[0]]:
                labels[ij] = (status, why)

        self.predicted = {ij: why for ij, why in self.predicted.items() if not self._rescanned(ij)}
        for ij, why in self.predicted.items():
            mark(ij, "at_risk", f"{why}; predicted before {self.change}, not re-scanned yet")
        for ij, why in self.cloud.risks(self.grid, t).items():
            mark(ij, "at_risk", why)
        for c, when in self.grid.cleared.items():
            mark((c[0], c[1]), "at_risk", f"scan diff: what stood here moved in {self.change} (seen clear at {when:.1f} s)")
        for c, when in self.grid.appeared.items():
            self.collapsed.setdefault((c[0], c[1]), f"scan diff: debris landed here in {self.change} (seen at {when:.1f} s)")
        for ij in self.collapsed:
            for n in _ring(ij, NEAR):
                mark(n, "at_risk", f"within 0.15 m of debris that fell in {self.change}")
        for ij, why in self.collapsed.items():
            labels[ij] = ("collapsed", why)
        self.labels = labels
        msg = self.message()
        if msg == self.last:
            return None
        self.last = msg
        return msg

    def message(self):
        return [{"cell": [i, j, k], "status": s, "why": why, "estimate": True}
                for (i, j), (s, why) in sorted(self.labels.items()) for k in LAYERS]

    def status(self, ij):
        return self.labels.get(tuple(ij[:2]), ("stable", ""))[0]
