// DEPTH-GAUGE: how far below ground each robot is, which floor it is on, and the deepest it has been.
//
// Read from the poses the console already gets (live, or a run replayed with replay_b2.ts / replay_b3.ts):
//   sensors/scout {pose: {pos: [x, y, z]}}   the Scout's body origin, 0.075 m above the floor it stands on
//   responder/pose {pos: [x, y, z]}          the Responder's chassis centre, 0.05 m above its floor
// The floor heights are the levels scene's (sim/scenes/make_levels.py, H = 0.6 m): L1 +0.6, ground 0, B1 -0.6,
// B2 -1.2, B3 -1.8. A robot within FLOOR_TOL_M of a floor is on it; otherwise it is on a ramp, between the two
// floors around it. Depth is metres below ground (0 at or above ground). Only poses move the gauge: nothing is
// interpolated or guessed, and a robot with no pose yet reads "no pose yet".
//
// DepthGauge is pure (no DOM, no bus import): apply(topic, data) and read `robots`. attachDepthGauge(on) subscribes
// it with bus.ts's on(), renderDepthGauge(el, gauge) draws it. Not wired into main.ts (console owner's call):
//   import { on } from './bus';
//   const gauge = attachDepthGauge(on);
//   gauge.onChange = () => renderDepthGauge(document.querySelector('#depth-gauge')!, gauge);

export const FLOORS: { id: string; z: number }[] = [
  { id: 'L1', z: 0.6 }, { id: 'ground', z: 0 }, { id: 'B1', z: -0.6 }, { id: 'B2', z: -1.2 }, { id: 'B3', z: -1.8 },
];
export const FLOOR_TOL_M = 0.03;   // the runners' own floor poses sit within 0.015 m of the floor; ramp ends come to 0.034 m
export const ORIGIN_Z = { scout: 0.075, responder: 0.05 } as const;

export type RobotId = 'scout' | 'responder';
export type Place = { floor: string } | { between: [string, string] };   // [upper, lower]
export type RobotDepth = {
  t: number | null;               // sim time of the last pose, if it carried one
  z: number;                      // floor-level z (pose z minus the body origin height), m
  depth: number;                  // m below ground, >= 0
  place: Place;
  deepest: { depth: number; place: Place; t: number | null };
  poses: number;
};

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const vecZ = (v: unknown): number | null =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(n => typeof n === 'number' && Number.isFinite(n)) ? v[2] as number : null;
const r3 = (x: number) => Math.round(x * 1000) / 1000;

/** Which floor a floor-level z is on, or the two floors it is between. Above L1 / below B3 clamp to them. */
export function placeAt(z: number): Place {
  const near = FLOORS.find(f => Math.abs(z - f.z) <= FLOOR_TOL_M);
  if (near) return { floor: near.id };
  if (z > FLOORS[0].z) return { floor: FLOORS[0].id };
  for (let i = 0; i + 1 < FLOORS.length; i++) {
    if (z < FLOORS[i].z && z > FLOORS[i + 1].z) return { between: [FLOORS[i].id, FLOORS[i + 1].id] };
  }
  return { floor: FLOORS[FLOORS.length - 1].id };
}

export const placeText = (p: Place) => ('floor' in p ? (p.floor === 'ground' ? 'ground floor' : p.floor)
  : `ramp between ${p.between[0]} and ${p.between[1]}`);

export class DepthGauge {
  robots: Partial<Record<RobotId, RobotDepth>> = {};
  onChange: ((robot: RobotId, d: RobotDepth) => void) | null = null;

  /** Feed one bus message. Returns the robot it moved, if any. */
  apply(topic: string, data: unknown): RobotId | null {
    if (!isRec(data)) return null;
    let robot: RobotId, z: number | null;
    if (topic === 'sensors/scout') { robot = 'scout'; z = isRec(data.pose) ? vecZ(data.pose.pos) : null; }
    else if (topic === 'responder/pose') { robot = 'responder'; z = vecZ(data.pos); }
    else return null;
    if (z === null) return null;
    const floorZ = r3(z - ORIGIN_Z[robot]);
    const depth = r3(Math.max(0, -floorZ));
    const place = placeAt(floorZ);
    const t = typeof data.t === 'number' && Number.isFinite(data.t) ? data.t : null;
    const prev = this.robots[robot];
    const deepest = !prev || depth > prev.deepest.depth ? { depth, place, t } : prev.deepest;
    const d: RobotDepth = { t, z: floorZ, depth, place, deepest, poses: (prev?.poses ?? 0) + 1 };
    this.robots[robot] = d;
    this.onChange?.(robot, d);
    return robot;
  }
}

/** Subscribe a DepthGauge to the console bus, given its on() (bus.ts). */
export function attachDepthGauge(on: (topic: string, handler: (data: unknown) => void) => unknown,
                                 gauge = new DepthGauge()): DepthGauge {
  for (const topic of ['sensors/scout', 'responder/pose']) on(topic, data => { gauge.apply(topic, data); });
  return gauge;
}

const NAMES: Record<RobotId, string> = { scout: 'Scout', responder: 'Responder' };

/** One line per robot, e.g. "Scout: B2, 1.2 m below ground (deepest B3, 1.8 m)". */
export function describeDepth(id: RobotId, d: RobotDepth | undefined): string {
  if (!d) return `${NAMES[id]}: no pose yet`;
  const here = d.depth > 0 ? `${d.depth.toFixed(1)} m below ground` : 'at or above ground';
  const deeper = d.deepest.depth > d.depth + 0.05 ? ` (deepest ${placeText(d.deepest.place)}, ${d.deepest.depth.toFixed(1)} m)` : '';
  return `${NAMES[id]}: ${placeText(d.place)}, ${here}${deeper}`;
}

// ---- drawing -------------------------------------------------------------------------------------------

const STYLE_ID = 'depth-gauge-style';
const CSS = `
.depth-gauge { --dg-bg: rgba(10, 16, 29, 0.9); --dg-line: #23334d; --dg-text: #e8f0fa; --dg-dim: #7f93b0;
  --dg-scout: #60a5fa; --dg-responder: #34d399; --dg-earth: #1a2638; display: grid; grid-template-columns: 7.5rem 1fr;
  gap: 0.75rem; align-items: stretch; max-width: 24rem; padding: 0.6rem 0.75rem; color: var(--dg-text);
  background: var(--dg-bg); border: 1px solid var(--dg-line); border-radius: 8px; font: 12px/1.4 Inter, system-ui, sans-serif; }
.depth-gauge .dg-scale { position: relative; height: 9rem; margin-left: 3.2rem; border-left: 1px solid var(--dg-line); }
.depth-gauge .dg-earth { position: absolute; left: 0; right: 0; bottom: 0; background: var(--dg-earth); }
.depth-gauge .dg-floor { position: absolute; left: 0; width: 100%; border-top: 1px dashed var(--dg-line); }
.depth-gauge .dg-floor span { position: absolute; right: calc(100% + 0.45rem); top: -0.7em; color: var(--dg-dim); white-space: nowrap; }
.depth-gauge .dg-floor[data-floor="ground"] { border-top: 1px solid var(--dg-dim); }
.depth-gauge .dg-mark { position: absolute; width: 0.7rem; height: 0.7rem; margin-top: -0.35rem; border-radius: 50%;
  border: 2px solid var(--dg-bg); box-sizing: content-box; }
.depth-gauge .dg-mark[data-robot="scout"] { left: 0.6rem; background: var(--dg-scout); }
.depth-gauge .dg-mark[data-robot="responder"] { left: 1.9rem; background: var(--dg-responder); }
.depth-gauge .dg-deepest { position: absolute; width: 0.9rem; border-top: 2px solid; opacity: 0.6; }
.depth-gauge .dg-deepest[data-robot="scout"] { left: 0.5rem; border-color: var(--dg-scout); }
.depth-gauge .dg-deepest[data-robot="responder"] { left: 1.8rem; border-color: var(--dg-responder); }
.depth-gauge ul { margin: 0; padding: 0; list-style: none; align-self: center; }
.depth-gauge li { padding-left: 0.9rem; position: relative; }
.depth-gauge li + li { margin-top: 0.35rem; }
.depth-gauge li::before { content: ''; position: absolute; left: 0; top: 0.4em; width: 0.5rem; height: 0.5rem; border-radius: 50%; }
.depth-gauge li[data-robot="scout"]::before { background: var(--dg-scout); }
.depth-gauge li[data-robot="responder"]::before { background: var(--dg-responder); }
.depth-gauge li[data-pose="false"] { color: var(--dg-dim); }
`;

/** Draw (or redraw) the gauge into el. The readout is a polite live region; the scale is decorative. */
export function renderDepthGauge(el: HTMLElement, gauge: DepthGauge): HTMLElement {
  const doc = el.ownerDocument;
  if (!doc.getElementById(STYLE_ID)) {
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    doc.head.appendChild(style);
  }
  const top = FLOORS[0].z + 0.15, bottom = FLOORS[FLOORS.length - 1].z - 0.15;
  const pct = (z: number) => `${(((top - Math.min(top, Math.max(bottom, z))) / (top - bottom)) * 100).toFixed(1)}%`;
  const box = doc.createElement('section');
  box.className = 'depth-gauge';
  box.setAttribute('aria-label', 'Depth below ground');
  const scale = doc.createElement('div');
  scale.className = 'dg-scale';
  scale.setAttribute('aria-hidden', 'true');
  const earth = doc.createElement('div');
  earth.className = 'dg-earth';
  earth.style.top = pct(0);
  scale.appendChild(earth);
  for (const f of FLOORS) {
    const line = doc.createElement('div');
    line.className = 'dg-floor';
    line.dataset.floor = f.id;
    line.style.top = pct(f.z);
    const label = doc.createElement('span');
    label.textContent = f.id;
    line.appendChild(label);
    scale.appendChild(line);
  }
  const list = doc.createElement('ul');
  list.setAttribute('aria-live', 'polite');
  for (const id of ['scout', 'responder'] as RobotId[]) {
    const d = gauge.robots[id];
    if (d) {
      const deep = doc.createElement('div');
      deep.className = 'dg-deepest';
      deep.dataset.robot = id;
      deep.style.top = pct(-d.deepest.depth);
      const mark = doc.createElement('div');
      mark.className = 'dg-mark';
      mark.dataset.robot = id;
      mark.style.top = pct(d.z);
      scale.append(deep, mark);
    }
    const li = doc.createElement('li');
    li.dataset.robot = id;
    li.dataset.pose = String(!!d);
    li.textContent = describeDepth(id, d);
    list.appendChild(li);
  }
  box.append(scale, list);
  el.replaceChildren(box);
  return box;
}
