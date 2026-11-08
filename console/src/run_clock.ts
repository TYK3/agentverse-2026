// RUN-CLOCK: the run's sim time in the console, following a real run log's own t.
//
// - runSpan(text) reads any run log or recording on main, one JSON object per line with a "t" in sim seconds
//   (tools/run_levels.py, tools/run_b2.py, console recordings {t, topic, data}): first and last t, records, and
//   lines it could not read. That is the clock's length.
// - RunClock follows sim time as the run plays, from the bus: ReplayPlayer's console/replay status {t, state,
//   speed, file} (replay-jsonl.ts), and the t that sim messages carry (sensors/scout, responder/pose,
//   world/change, log/decision ...). It never runs backwards, except when a replay starts over (state ready,
//   or a new file), and never runs on its own between messages: it shows the last t the run reported.
// - It says where the time comes from: "Replay" (from a log, with its speed) or "Live" (sim messages only).
// - renderRunClock(el, clock) draws m:ss.s, the run's length when known, and a progress bar.
// Pure parts have no DOM and no bus import. Not wired into main.ts (console owner's call):
//   import { on } from './bus';
//   const clock = attachRunClock(on, runSpan(logText));
//   clock.onChange = () => renderRunClock(document.querySelector('#run-clock')!, clock);

export type RunSpan = { start: number; end: number; records: number; issues: { line: number; reason: string }[] };

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** The sim-time span of a run log (see the header). An empty log spans 0..0. */
export function runSpan(text: string): RunSpan {
  const issues: { line: number; reason: string }[] = [];
  let start = Infinity, end = -Infinity, records = 0;
  text.split(/\r?\n/).forEach((raw, i) => {
    if (!raw.trim()) return;
    let v: unknown;
    try { v = JSON.parse(raw); } catch { return void issues.push({ line: i + 1, reason: 'not JSON' }); }
    const t = isRec(v) ? num(v.t) : null;
    if (t === null || t < 0) return void issues.push({ line: i + 1, reason: 'no sim time t' });
    records += 1;
    start = Math.min(start, t);
    end = Math.max(end, t);
  });
  return records ? { start, end, records, issues } : { start: 0, end: 0, records: 0, issues };
}

/** m:ss.s (or h:mm:ss.s past an hour), from sim seconds. */
export function formatSimTime(t: number): string {
  const tenths = Math.max(0, Math.round(t * 10));
  const s = (tenths % 600) / 10, m = Math.floor(tenths / 600) % 60, h = Math.floor(tenths / 36000);
  const ss = s.toFixed(1).padStart(4, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

export type ClockSource = 'replay' | 'live' | 'none';

export class RunClock {
  t = 0;                          // sim seconds, the last the run reported
  end: number | null;             // the run's length, when known (a loaded log, or a replay that finished)
  source: ClockSource = 'none';
  state: string | null = null;    // replay state: ready | playing | paused | done | stopped
  speed: number | null = null;
  file: string | null = null;
  onChange: ((c: RunClock) => void) | null = null;

  constructor(span?: RunSpan) { this.end = span && span.records ? span.end : null; }

  /** Feed one bus message. Returns true if the clock changed. */
  apply(topic: string, data: unknown): boolean {
    if (!isRec(data)) return false;
    const before = `${this.t}|${this.end}|${this.source}|${this.state}|${this.speed}|${this.file}`;
    if (topic === 'console/replay') {
      const t = num(data.t);
      const file = typeof data.file === 'string' ? data.file : null;
      const state = typeof data.state === 'string' ? data.state : null;
      if (state === 'ready' || (file !== null && this.file !== null && file !== this.file)) this.t = 0;   // starts over
      this.source = 'replay';
      this.state = state;
      this.speed = num(data.speed);
      this.file = file;
      if (t !== null) this.t = Math.max(this.t, t);
      if (state === 'done' && this.end === null) this.end = this.t;
    } else if (topic === 'scene/loaded' && this.source !== 'replay') {
      this.t = 0;
      this.source = 'live';
    } else {
      const t = num(data.t);
      if (t === null || t < 0) return false;
      if (this.source === 'none') this.source = 'live';
      this.t = Math.max(this.t, t);
    }
    const changed = before !== `${this.t}|${this.end}|${this.source}|${this.state}|${this.speed}|${this.file}`;
    if (changed) this.onChange?.(this);
    return changed;
  }

  /** 0..1 through the run, when its length is known. */
  get progress(): number | null {
    return this.end && this.end > 0 ? Math.min(1, this.t / this.end) : null;
  }

  /** One line, e.g. "Replay sim time 3:45.8 of 3:50.9, playing at 4x". */
  describe(): string {
    if (this.source === 'none') return 'Sim time: waiting for the run';
    const of = this.end !== null ? ` of ${formatSimTime(this.end)}` : '';
    const how = this.source === 'replay'
      ? `${this.state ? `, ${this.state}` : ''}${this.speed && this.state === 'playing' ? ` at ${this.speed}x` : ''}` : '';
    return `${this.source === 'replay' ? 'Replay' : 'Live'} sim time ${formatSimTime(this.t)}${of}${how}`;
  }
}

/** Subscribe a RunClock to the console bus, given its on() (bus.ts). */
export function attachRunClock(on: (topic: string, handler: (data: unknown) => void) => unknown,
                               span?: RunSpan, clock = new RunClock(span)): RunClock {
  for (const topic of ['console/replay', 'scene/loaded', 'sensors/scout', 'responder/pose', 'world/change',
                       'log/decision', 'permit/route', 'casualty/reply', 'casualty/contact', 'map/cells', 'map/points']) {
    on(topic, data => { clock.apply(topic, data); });
  }
  return clock;
}

// ---- drawing -------------------------------------------------------------------------------------------

const STYLE_ID = 'run-clock-style';
const CSS = `
.run-clock { --rc-bg: rgba(10, 16, 29, 0.9); --rc-line: #23334d; --rc-text: #e8f0fa; --rc-dim: #7f93b0; --rc-fill: #60a5fa;
  display: inline-grid; grid-template-columns: auto auto; column-gap: 0.6rem; align-items: baseline; min-width: 11rem;
  padding: 0.4rem 0.7rem 0.45rem; color: var(--rc-text); background: var(--rc-bg); border: 1px solid var(--rc-line);
  border-radius: 8px; font: 12px/1.3 Inter, system-ui, sans-serif; }
.run-clock .rc-src { color: var(--rc-dim); }
.run-clock[data-source="replay"] .rc-src { color: #fbbf24; }
.run-clock .rc-now { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: 0.01em; }
.run-clock .rc-of { color: var(--rc-dim); font-variant-numeric: tabular-nums; }
.run-clock .rc-bar { grid-column: 1 / -1; height: 3px; margin-top: 0.35rem; background: var(--rc-line); border-radius: 2px; overflow: hidden; }
.run-clock .rc-bar span { display: block; height: 100%; background: var(--rc-fill); }
`;

/** Draw (or redraw) the clock into el. The full sentence is its accessible label; the bar is a progressbar. */
export function renderRunClock(el: HTMLElement, clock: RunClock): HTMLElement {
  const doc = el.ownerDocument;
  if (!doc.getElementById(STYLE_ID)) {
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    doc.head.appendChild(style);
  }
  const box = doc.createElement('div');
  box.className = 'run-clock';
  box.dataset.source = clock.source;
  box.setAttribute('role', 'timer');
  box.setAttribute('aria-label', clock.describe());
  const src = doc.createElement('span');
  src.className = 'rc-src';
  src.textContent = clock.source === 'replay' ? `Replay${clock.state && clock.state !== 'playing' ? `, ${clock.state}` : ''}`
    : clock.source === 'live' ? 'Live' : 'Waiting';
  const of = doc.createElement('span');
  of.className = 'rc-of';
  of.textContent = clock.end !== null ? `of ${formatSimTime(clock.end)}` : 'sim time';
  const now = doc.createElement('span');
  now.className = 'rc-now';
  now.textContent = formatSimTime(clock.t);
  box.append(src, of, now);
  if (clock.speed && clock.source === 'replay') {
    const sp = doc.createElement('span');
    sp.className = 'rc-of';
    sp.textContent = `${clock.speed}x`;
    box.appendChild(sp);
  }
  const p = clock.progress;
  if (p !== null) {
    const bar = doc.createElement('div');
    bar.className = 'rc-bar';
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', 'Through the run');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    bar.setAttribute('aria-valuenow', String(Math.round(p * 100)));
    const fill = doc.createElement('span');
    fill.style.width = `${(p * 100).toFixed(1)}%`;
    bar.appendChild(fill);
    box.appendChild(bar);
  }
  el.replaceChildren(box);
  return box;
}
