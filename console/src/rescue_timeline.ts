// RESCUE-TIMELINE: the stages of a real rescue run, from its log, as a timeline the console can draw.
//
// Reads the two run logs on main (one {"t": sim seconds, "kind": ...} record per line):
//   tools/run_levels.py  runs/levels-<seed>.jsonl  B1 > B2 > B3 chain: meta, level, pose, plan, leg, summary, step
//   tools/run_b2.py      runs/b2-<seed>.jsonl, runs/b3-<seed>.jsonl (--floor B3): level, pose, plan, shift,
//                        mapped, summary, verdict
// buildRescueTimeline(text) gives:
//   stages  one per floor the Scout drove onto, in order, from that `level` record to the next (the last runs to
//           the end of the log), each with what happened on it: casualties reached, the slab shift, the recheck
//   events  time-ordered marks: floor reached, casualty reached, slab shift, slab mapped, first re-plan after it
//   checks  the runner's own verdict (step records, or the verdict record): passed / total and what failed
// Only what the log says: times are sim seconds from the log, never wall time; a casualty the log does not
// mark reached is not drawn as reached; checks are copied, not re-judged. Bad lines are issues, never thrown.
//
// renderRescueTimeline(el, timeline) draws it as a descent profile (SVG): time across, floors down, the
// Scout's line stepping down floor by floor, with the marks on it. Not wired into main.ts (console owner's
// call). Pure data part, no DOM on import:
//   const tl = buildRescueTimeline(await (await fetch('/runs/levels-0.jsonl')).text());
//   renderRescueTimeline(document.querySelector('#timeline')!, tl);

export type RunKind = 'run_levels' | 'run_b2' | 'unknown';
export type EventKind = 'floor' | 'casualty' | 'shift' | 'mapped' | 'recheck';
export type TimelineEvent = { t: number; kind: EventKind; floor: string | null; label: string };
export type Stage = {
  floor: string;
  start: number;
  end: number;
  casualties: { id: string | null; t: number }[];   // reached on this floor
  shift: number | null;                                // slab shift on this floor, sim s
  recheck: number | null;                              // first re-plan after that shift
};
export type Check = { name: string; ok: boolean; t: number | null; detail: string };
export type RescueTimeline = {
  run: RunKind;
  seed: number | null;
  target: string | null;          // deepest floor the run was after
  end: number;                    // last record's sim time
  stages: Stage[];
  events: TimelineEvent[];
  checks: Check[];
  passed: number;
  total: number;
  ok: boolean;                    // every check passed (false with no checks)
  issues: { line: number; reason: string }[];
};

/** Floors top to bottom: the profile's rows. Unknown floors are added below, in the order seen. */
export const FLOOR_ORDER = ['L2', 'L1', 'ground', 'B1', 'B2', 'B3'];

type Rec = Record<string, unknown> & { t: number; kind: string };
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const KINDS = new Set(['meta', 'level', 'pose', 'plan', 'leg', 'summary', 'step', 'shift', 'mapped', 'verdict']);

/** Build the timeline from a run log's text (see the header). */
export function buildRescueTimeline(text: string): RescueTimeline {
  const issues: { line: number; reason: string }[] = [];
  const recs: { rec: Rec; line: number }[] = [];
  let lastT = -Infinity;
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = i + 1;
    if (!raw.trim()) return;
    let v: unknown;
    try { v = JSON.parse(raw); } catch { return void issues.push({ line, reason: 'not JSON' }); }
    if (!isObj(v)) return void issues.push({ line, reason: 'not an object' });
    if (typeof v.kind !== 'string' || !KINDS.has(v.kind)) {
      return void issues.push({ line, reason: `unknown kind ${String(v.kind)}` });
    }
    if (typeof v.t !== 'number' || !Number.isFinite(v.t) || v.t < 0) return void issues.push({ line, reason: 'missing or invalid t' });
    if (v.t < lastT) issues.push({ line, reason: `time goes back (${v.t} after ${lastT}); kept in file order` });
    lastT = Math.max(lastT, v.t);
    recs.push({ rec: v as Rec, line });
  });

  const tl: RescueTimeline = { run: 'unknown', seed: null, target: null, end: 0, stages: [], events: [], checks: [],
                               passed: 0, total: 0, ok: false, issues };
  const has = (k: string) => recs.some(r => r.rec.kind === k);
  tl.run = has('leg') || has('step') || has('meta') ? 'run_levels' : has('verdict') || has('shift') ? 'run_b2' : 'unknown';

  let floor: string | null = null;
  let shiftT: number | null = null;
  let shiftStage: Stage | null = null;
  const ev = (t: number, kind: EventKind, label: string, f: string | null = floor) => tl.events.push({ t, kind, floor: f, label });

  for (const { rec, line } of recs) {
    const t = rec.t;
    tl.end = Math.max(tl.end, t);
    switch (rec.kind) {
      case 'meta':
        if (typeof rec.seed === 'number') tl.seed = rec.seed;
        if (Array.isArray(rec.legs) && rec.legs.length) tl.target = str(rec.legs[rec.legs.length - 1]);
        break;
      case 'level': {
        const f = str(rec.level);
        if (!f) { issues.push({ line, reason: 'level without a name' }); break; }
        const prev = tl.stages.at(-1);
        if (prev) prev.end = t;
        tl.stages.push({ floor: f, start: t, end: t, casualties: [], shift: null, recheck: null });
        floor = f;
        ev(t, 'floor', `On ${f}`);
        break;
      }
      case 'leg': {
        const f = str(rec.floor) ?? floor;
        const id = str(rec.casualty);
        if (rec.reached !== true) break;                  // only what the log marks reached
        const stage = [...tl.stages].reverse().find(s => s.floor === f) ?? tl.stages.at(-1);
        stage?.casualties.push({ id, t });
        ev(t, 'casualty', `Reached ${id ?? 'the casualty'} on ${f ?? 'an unknown floor'}`, f);
        break;
      }
      case 'shift': {
        const f = str(rec.level) ?? floor;
        shiftT = t;
        shiftStage = [...tl.stages].reverse().find(s => s.floor === f) ?? tl.stages.at(-1) ?? null;
        if (shiftStage) shiftStage.shift = t;
        ev(t, 'shift', `Slab shifted onto the route on ${f ?? 'an unknown floor'}`, f);
        break;
      }
      case 'mapped': {
        const n = typeof rec.cells === 'number' ? rec.cells : 0;
        ev(t, 'mapped', `Slab mapped from the Scout's own sensors (${n} cells)`);
        break;
      }
      case 'plan':
        if (shiftT !== null && shiftStage && shiftStage.recheck === null && t >= shiftT) {
          shiftStage.recheck = t;
          ev(t, 'recheck', 'Re-planned around the slab');
        }
        break;
      case 'summary': {
        const f = str(rec.floor);
        if (f) tl.target = f;
        break;
      }
      case 'step':
        tl.checks.push({ name: str(rec.name) ?? 'unnamed check', ok: rec.ok === true, t: null, detail: str(rec.detail) ?? '' });
        break;
      case 'verdict':
        if (isObj(rec.steps)) {
          for (const [name, s] of Object.entries(rec.steps)) {
            if (!isObj(s)) continue;
            tl.checks.push({ name, ok: s.ok === true, t: typeof s.t === 'number' ? s.t : null, detail: str(s.detail) ?? '' });
          }
        }
        break;
    }
  }
  const last = tl.stages.at(-1);
  if (last) last.end = tl.end;

  // run_b2 has no leg records: its casualty is the verdict's "reached the casualty" check, with its own time.
  if (tl.run === 'run_b2') {
    const reached = tl.checks.find(c => /reached the casualty/i.test(c.name));
    if (reached?.ok && reached.t !== null) {
      const f = tl.target ?? last?.floor ?? null;
      const stage = [...tl.stages].reverse().find(s => s.floor === f) ?? last;
      stage?.casualties.push({ id: null, t: reached.t });
      ev(reached.t, 'casualty', `Reached the casualty on ${f ?? 'an unknown floor'}`, f);
    }
  }
  if (!tl.target && last) tl.target = last.floor;
  tl.events.sort((a, b) => a.t - b.t);
  tl.total = tl.checks.length;
  tl.passed = tl.checks.filter(c => c.ok).length;
  tl.ok = tl.total > 0 && tl.passed === tl.total;
  return tl;
}

// ---- drawing -------------------------------------------------------------------------------------------

const SVG = 'http://www.w3.org/2000/svg';
const STYLE_ID = 'rescue-timeline-style';
const CSS = `
.rescue-timeline { --rt-text: #e8f0fa; --rt-dim: #7f93b0; --rt-line: #23334d; --rt-path: #60a5fa;
  --rt-shift: #f97316; --rt-done: #34d399; --rt-fail: #f87171; color: var(--rt-text); font: 12px/1.4 Inter, system-ui, sans-serif; }
.rescue-timeline figcaption { display: flex; gap: 0.75rem; align-items: baseline; margin: 0 0 0.35rem; }
.rescue-timeline figcaption strong { font-size: 13px; font-weight: 600; }
.rescue-timeline .rt-verdict { color: var(--rt-done); }
.rescue-timeline .rt-verdict[data-ok="false"] { color: var(--rt-fail); }
.rescue-timeline svg { display: block; width: 100%; height: auto; overflow: visible; }
.rescue-timeline .rt-band { fill: none; stroke: var(--rt-line); stroke-dasharray: 2 4; }
.rescue-timeline .rt-floor { fill: var(--rt-dim); font-size: 11px; }
.rescue-timeline .rt-tick { fill: var(--rt-dim); font-size: 10px; font-variant-numeric: tabular-nums; }
.rescue-timeline .rt-path { fill: none; stroke: var(--rt-path); stroke-width: 2.5; stroke-linejoin: round; }
.rescue-timeline .rt-casualty { fill: var(--rt-done); }
.rescue-timeline .rt-shift { fill: none; stroke: var(--rt-shift); stroke-width: 2; }
.rescue-timeline .rt-recheck { fill: none; stroke: var(--rt-shift); stroke-width: 1.5; stroke-dasharray: 2 2; }
.rescue-timeline .rt-mark:focus-visible { outline: 2px solid var(--rt-path); outline-offset: 2px; }
`;

const fmtT = (t: number) => `${Math.round(t * 10) / 10} s`;

/** Floors as profile rows, top to bottom: the known order, then anything else in the order seen. */
export function profileFloors(tl: RescueTimeline): string[] {
  const seen = tl.stages.map(s => s.floor);
  const known = FLOOR_ORDER.filter(f => seen.includes(f));
  return [...known, ...seen.filter((f, i) => !FLOOR_ORDER.includes(f) && seen.indexOf(f) === i)];
}

/** One sentence for screen readers and the figure's label. */
export function describeTimeline(tl: RescueTimeline): string {
  if (!tl.stages.length) return 'No floors in this run log.';
  const path = tl.stages.map(s => s.floor).join(', then ');
  const people = tl.events.filter(e => e.kind === 'casualty').length;
  const shift = tl.events.find(e => e.kind === 'shift');
  return [`The Scout drove ${path} in ${fmtT(tl.end)}.`,
          people ? `It reached ${people} ${people === 1 ? 'casualty' : 'casualties'}.` : 'It reached no casualty.',
          shift ? `A slab shifted at ${fmtT(shift.t)} and it re-planned.` : '',
          tl.total ? `${tl.passed} of ${tl.total} checks passed.` : 'The log has no checks.'].filter(Boolean).join(' ');
}

/** Draw the timeline into el (replacing its content). Returns the figure. */
export function renderRescueTimeline(el: HTMLElement, tl: RescueTimeline, opts: { width?: number } = {}): HTMLElement {
  const doc = el.ownerDocument;
  if (!doc.getElementById(STYLE_ID)) {
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    doc.head.appendChild(style);
  }
  const fig = doc.createElement('figure');
  fig.className = 'rescue-timeline';
  fig.style.margin = '0';
  const cap = doc.createElement('figcaption');
  const title = doc.createElement('strong');
  title.textContent = tl.seed !== null ? `Rescue run, seed ${tl.seed}` : 'Rescue run';
  const verdict = doc.createElement('span');
  verdict.className = 'rt-verdict';
  verdict.dataset.ok = String(tl.ok);
  verdict.textContent = tl.total ? `${tl.passed} of ${tl.total} checks passed` : 'No checks in this log';
  cap.append(title, verdict);
  fig.appendChild(cap);

  const floors = profileFloors(tl);
  const W = opts.width ?? 640;
  const left = 52, right = 12, top = 10, row = 22, axis = 18;
  const H = top + Math.max(1, floors.length) * row + axis;
  const span = Math.max(tl.end, 1);
  const x = (t: number) => left + (t / span) * (W - left - right);
  const y = (f: string) => top + (floors.indexOf(f) + 0.5) * row;

  const svg = doc.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', describeTimeline(tl));
  const add = (tag: string, attrs: Record<string, string | number>, text?: string) => {
    const n = doc.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    if (text !== undefined) n.textContent = text;
    svg.appendChild(n);
    return n;
  };
  for (const f of floors) {
    add('line', { class: 'rt-band', x1: left, x2: W - right, y1: y(f), y2: y(f) });
    add('text', { class: 'rt-floor', x: left - 8, y: y(f) + 4, 'text-anchor': 'end' }, f);
  }
  const tickStep = span > 600 ? 120 : span > 240 ? 60 : 30;
  for (let t = 0; t <= span + 1e-9; t += tickStep) {
    add('text', { class: 'rt-tick', x: x(t), y: H - 4, 'text-anchor': 'middle' }, t === 0 ? '0' : `${t} s`);
  }
  // the Scout's line: level on each floor for its stage, a step down where it reached the next one
  const d = tl.stages.map((s, i) => `${i ? 'L' : 'M'}${x(s.start).toFixed(1)},${y(s.floor).toFixed(1)} H${x(s.end).toFixed(1)}`)
    .join(' ');
  if (d) add('path', { class: 'rt-path', d });
  const mark = (node: Element, label: string) => {
    node.setAttribute('class', `${node.getAttribute('class')} rt-mark`);
    node.setAttribute('tabindex', '0');
    node.setAttribute('aria-label', label);
    const t = doc.createElementNS(SVG, 'title');
    t.textContent = label;
    node.appendChild(t);
  };
  for (const e of tl.events) {
    if (!e.floor || !floors.includes(e.floor)) continue;
    const cx = x(e.t), cy = y(e.floor), label = `${e.label}, ${fmtT(e.t)}`;
    if (e.kind === 'casualty') mark(add('circle', { class: 'rt-casualty', cx, cy, r: 5 }), label);
    else if (e.kind === 'shift') {
      mark(add('path', { class: 'rt-shift', d: `M${cx - 5},${cy - 9} l3,5 l-3,4 l5,0 l-2,-4 l4,-5` }), label);
    } else if (e.kind === 'recheck') mark(add('circle', { class: 'rt-recheck', cx, cy, r: 7 }), label);
  }
  fig.appendChild(svg);
  el.replaceChildren(fig);
  return fig;
}

/** Fetch a run log and build its timeline. Throws if the file cannot be fetched. */
export async function loadRescueTimeline(url: string): Promise<RescueTimeline> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`run log ${url}: HTTP ${res.status}`);
  return buildRescueTimeline(await res.text());
}
