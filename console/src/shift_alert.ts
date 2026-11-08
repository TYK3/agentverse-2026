// SHIFT-ALERT: when a slab shifts onto the Scout's route, say what the Scout did about it, step by step.
//
// The map's banner says an aftershock happened. This follows the Scout's own response to each shift, from the
// bus messages it already gets (live, or a run replayed with replay_b2.ts / replay_b3.ts):
//   world/change {kind: 'aftershock', moved_blocks, t}              -> a new alert: shifted
//   log/decision {outcome: 'stop_and_recheck', perception}           -> stopped (the floor comes from "... on B2")
//   log/decision {outcome: 'mapped', perception: 'N slab cell(s) ...'} -> mapped, with the cell count
//   route/proposed {robot: 'scout', id} after the shift               -> re-planned: the alert is resolved
// Each step keeps its sim time (the message's t, else the Scout's last t), so the alert can say how long the
// re-plan took in sim seconds. Nothing is assumed: a step the bus never reports stays open, and a second
// shift opens a second alert. A world/change that is not an aftershock (block_added) is ignored.
//
// ShiftAlerts is pure (no DOM, no bus import): apply(topic, data) and read `alerts`. attachShiftAlerts(on)
// subscribes it with the bus's on() and renderShiftAlert() draws the latest alert. Not wired into main.ts
// (console owner's call):
//   import { on } from './bus';
//   const alerts = attachShiftAlerts(on);
//   alerts.onChange = a => renderShiftAlert(document.querySelector('#shift-alert')!, a);

export type ShiftStep = 'shifted' | 'stopped' | 'mapped' | 'replanned';
export const STEPS: ShiftStep[] = ['shifted', 'stopped', 'mapped', 'replanned'];

export type ShiftAlert = {
  n: number;                      // 1 for the first shift seen, then 2, ...
  moved: string[];
  floor: string | null;
  t: Partial<Record<ShiftStep, number | null>>;   // sim time of each step reached (null: reached, time unknown)
  cells: number | null;           // slab cells the Scout mapped from its own sensors
  route: string | null;           // id of the first Scout route after the shift
  resolved: boolean;              // re-planned
};

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export class ShiftAlerts {
  alerts: ShiftAlert[] = [];
  onChange: ((latest: ShiftAlert) => void) | null = null;
  private lastT: number | null = null;
  private floor: string | null = null;

  get latest(): ShiftAlert | null { return this.alerts.at(-1) ?? null; }

  /** Feed one bus message. Returns the alert it changed, if any. */
  apply(topic: string, data: unknown): ShiftAlert | null {
    if (!isRec(data)) return null;
    const t = num(data.t);
    if (t !== null) this.lastT = t;
    const when = t ?? this.lastT;
    const open = this.latest && !this.latest.resolved ? this.latest : null;
    switch (topic) {
      case 'world/change': {
        if (data.kind !== 'aftershock') return null;
        const moved = Array.isArray(data.moved_blocks) ? data.moved_blocks.filter((b): b is string => typeof b === 'string') : [];
        const alert: ShiftAlert = { n: this.alerts.length + 1, moved, floor: this.floor, t: { shifted: when },
                                    cells: null, route: null, resolved: false };
        this.alerts.push(alert);
        return this.changed(alert);
      }
      case 'log/decision': {
        const perception = typeof data.perception === 'string' ? data.perception : '';
        const level = /^Scout on (\S+?)(,|$)/.exec(perception);
        if (level) this.floor = level[1];
        if (!open) return null;
        if (data.outcome === 'stop_and_recheck' && !('stopped' in open.t)) {
          const on = / on (\S+)$/.exec(perception);
          if (on) open.floor = on[1];
          open.t.stopped = when;
          return this.changed(open);
        }
        if (data.outcome === 'mapped' && !('mapped' in open.t)) {
          const cells = /^(\d+) slab cell/.exec(perception);
          open.cells = cells ? Number(cells[1]) : null;
          open.t.mapped = when;
          return this.changed(open);
        }
        return null;
      }
      case 'route/proposed': {
        if (!open || data.robot !== 'scout') return null;
        const shifted = open.t.shifted;
        if (when !== null && shifted !== null && shifted !== undefined && when < shifted) return null;
        open.t.replanned = when;
        open.route = typeof data.id === 'string' ? data.id : null;
        open.resolved = true;
        return this.changed(open);
      }
      default:
        return null;
    }
  }

  private changed(a: ShiftAlert): ShiftAlert {
    this.onChange?.(a);
    return a;
  }
}

/** Subscribe a ShiftAlerts to the console bus, given its on() (bus.ts). */
export function attachShiftAlerts(on: (topic: string, handler: (data: unknown) => void) => unknown,
                                  alerts = new ShiftAlerts()): ShiftAlerts {
  for (const topic of ['world/change', 'log/decision', 'route/proposed', 'sensors/scout']) {
    on(topic, data => { alerts.apply(topic, data); });
  }
  return alerts;
}

const fmt = (t: number) => `${Math.round(t * 10) / 10} s`;

/** The alert as plain lines: a headline and one line per step, done or still open. */
export function describeShiftAlert(a: ShiftAlert): { headline: string; steps: { step: ShiftStep; done: boolean; text: string }[] } {
  const where = a.floor ? ` on ${a.floor}` : '';
  const headline = a.resolved ? `Slab shift${where}: Scout re-planned around it` : `Slab shifted onto the Scout's route${where}`;
  const at = (s: ShiftStep) => { const v = a.t[s]; return typeof v === 'number' ? ` at ${fmt(v)}` : ''; };
  const since = (s: ShiftStep) => {
    const v = a.t[s], s0 = a.t.shifted;
    if (typeof v !== 'number' || typeof s0 !== 'number') return '';
    return v - s0 < 0.05 ? ' at once' : `, ${fmt(v - s0)} after the shift`;
  };
  const moved = a.moved.length ? ` (${a.moved.join(', ')} moved)` : '';
  return {
    headline,
    steps: [
      { step: 'shifted', done: true, text: `Slab landed on the route${at('shifted')}${moved}` },
      { step: 'stopped', done: 'stopped' in a.t, text: 'stopped' in a.t ? `Scout stopped short${since('stopped')}` : 'Waiting for the Scout to stop' },
      { step: 'mapped', done: 'mapped' in a.t,
        text: 'mapped' in a.t ? `Slab mapped from the Scout's own sensors${a.cells !== null ? ` (${a.cells} cells)` : ''}`
          : 'Waiting for the Scout to map the slab' },
      { step: 'replanned', done: a.resolved,
        text: a.resolved ? `New route${a.route ? ` ${a.route}` : ''}${since('replanned')}` : 'Waiting for a new route' },
    ],
  };
}

// ---- drawing -------------------------------------------------------------------------------------------

const STYLE_ID = 'shift-alert-style';
const CSS = `
.shift-alert { --sa-bg: rgba(10, 16, 29, 0.92); --sa-line: #23334d; --sa-text: #e8f0fa; --sa-dim: #7f93b0;
  --sa-shift: #f97316; --sa-done: #34d399; position: relative; max-width: 26rem; padding: 0.55rem 0.75rem 0.6rem 0.9rem;
  color: var(--sa-text); background: var(--sa-bg); border: 1px solid var(--sa-line); border-left: 4px solid var(--sa-shift);
  border-radius: 8px; font: 13px/1.45 Inter, system-ui, sans-serif; }
.shift-alert[data-resolved="true"] { border-left-color: var(--sa-done); }
.shift-alert h3 { margin: 0 1.8rem 0.3rem 0; font-size: 13px; font-weight: 600; }
.shift-alert ol { margin: 0; padding: 0; list-style: none; }
.shift-alert li { position: relative; padding-left: 1.1rem; color: var(--sa-dim); }
.shift-alert li::before { content: ''; position: absolute; left: 0.1rem; top: 0.45em; width: 0.5rem; height: 0.5rem;
  border-radius: 50%; border: 1.5px solid var(--sa-dim); box-sizing: border-box; }
.shift-alert li[data-done="true"] { color: var(--sa-text); }
.shift-alert li[data-done="true"]::before { background: var(--sa-done); border-color: var(--sa-done); }
.shift-alert li[data-step="shifted"]::before { background: var(--sa-shift); border-color: var(--sa-shift); }
.shift-alert button { position: absolute; top: 0.35rem; right: 0.4rem; padding: 0.1rem 0.4rem; color: var(--sa-dim);
  background: none; border: 1px solid transparent; border-radius: 4px; font: inherit; cursor: pointer; }
.shift-alert button:hover { color: var(--sa-text); border-color: var(--sa-line); }
.shift-alert button:focus-visible { outline: 2px solid #60a5fa; outline-offset: 1px; }
`;

/** Draw (or redraw) an alert into el; null clears it. Polite live region, so each step is read out once. */
export function renderShiftAlert(el: HTMLElement, a: ShiftAlert | null): HTMLElement | null {
  const doc = el.ownerDocument;
  if (!doc.getElementById(STYLE_ID)) {
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    doc.head.appendChild(style);
  }
  el.setAttribute('aria-live', 'polite');
  if (!a) { el.replaceChildren(); return null; }
  const d = describeShiftAlert(a);
  const box = doc.createElement('section');
  box.className = 'shift-alert';
  box.dataset.resolved = String(a.resolved);
  box.dataset.n = String(a.n);
  const h = doc.createElement('h3');
  h.textContent = d.headline;
  const list = doc.createElement('ol');
  for (const s of d.steps) {
    const li = doc.createElement('li');
    li.dataset.step = s.step;
    li.dataset.done = String(s.done);
    li.textContent = s.text;
    list.appendChild(li);
  }
  const close = doc.createElement('button');
  close.type = 'button';
  close.textContent = 'Dismiss';
  close.setAttribute('aria-label', 'Dismiss the slab shift alert');
  close.addEventListener('click', () => el.replaceChildren());
  box.append(h, list, close);
  el.replaceChildren(box);
  return box;
}
