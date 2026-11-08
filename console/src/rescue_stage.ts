// CONSOLE-STAGE: which stage the rescue is in at any sim time, from a real run log, as one line the console
// can show (a stage pill over the map, or beside a replay's scrubber).
//
// Reads the two run logs on main, one {"t": sim seconds, "kind": ...} record per line:
//   tools/run_levels.py  runs/levels-<seed>.jsonl  B1 > B2 > B3: meta {legs}, level, pose, plan, leg, summary, step
//   tools/run_b2.py      runs/b2-<seed>.jsonl, runs/b3-<seed>.jsonl: level, pose, plan, shift, mapped, summary, verdict
// Stages, in the order a rescue goes through them:
//   start    before the first level record
//   descend  on a floor (or a ramp) above the floor of the casualty being sought
//   search   on that casualty's floor, not reached yet (also: driving again after a re-plan)
//   shift    a slab has landed on the route: the Scout stops
//   recheck  the first re-plan after the shift, until the Scout drives again
//   reached  a casualty reached (run_levels: its leg record; run_b2: the verdict's own time for it)
//   done     the runner's verdict: n of m checks passed
// rescueStages(text) gives the stage changes in time order; stageAt(stages, t) the stage at sim time t.
// Only what the log says: sim seconds, never wall time; a casualty not marked reached is never "reached";
// the target floors are the log's own (meta.legs, else summary.floor, else the deepest level it logs).
// Bad lines are issues, never thrown. renderRescueStage(el, stage) draws the pill. Not wired into main.ts.
//   const { stages } = rescueStages(await (await fetch('/runs/b3-0.jsonl')).text());
//   renderRescueStage(document.querySelector('#rescue-stage')!, stageAt(stages, replayT));

export type StageId = 'start' | 'descend' | 'search' | 'shift' | 'recheck' | 'reached' | 'done';
export const STAGE_ORDER: StageId[] = ['start', 'descend', 'search', 'shift', 'recheck', 'reached', 'done'];

export type RescueStage = {
  t: number;
  stage: StageId;
  floor: string | null;           // the floor (or 'ramp') the Scout is on
  target: string | null;          // the floor of the casualty being sought
  casualty: string | null;        // its id, when the log names it
  label: string;
  ok?: boolean;                   // done: every check passed
};
export type RescueStages = { stages: RescueStage[]; targets: string[]; issues: { line: number; reason: string }[] };

type Rec = Record<string, unknown> & { t: number; kind: string };
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const KINDS = new Set(['meta', 'level', 'pose', 'plan', 'leg', 'summary', 'step', 'shift', 'mapped', 'verdict']);
const BASEMENT_ORDER = ['L2', 'L1', 'ground', 'B1', 'B2', 'B3'];

const fmtFloor = (f: string | null) => (f === 'ground' ? 'the ground floor' : f === 'ramp' ? 'a ramp' : f ?? 'an unknown floor');

export function stageLabel(s: Omit<RescueStage, 'label'>, passed?: number, total?: number): string {
  const who = s.casualty ?? 'the casualty';
  switch (s.stage) {
    case 'start': return 'Waiting for the run to start';
    case 'descend': return `Descending: on ${fmtFloor(s.floor)}, heading for ${fmtFloor(s.target)}`;
    case 'search': return `Searching ${fmtFloor(s.target)} for ${who}`;
    case 'shift': return `Slab shifted on ${fmtFloor(s.floor)}: Scout stopping`;
    case 'recheck': return `Re-planning around the slab on ${fmtFloor(s.floor)}`;
    case 'reached': return `Reached ${who} on ${fmtFloor(s.target)}`;
    case 'done': return total ? `Run over: ${passed} of ${total} checks passed` : 'Run over: no checks in the log';
  }
}

/** The stage changes of a run log, in time order (see the header). */
export function rescueStages(text: string): RescueStages {
  const issues: { line: number; reason: string }[] = [];
  const recs: Rec[] = [];
  let lastT = -Infinity;
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = i + 1;
    if (!raw.trim()) return;
    let v: unknown;
    try { v = JSON.parse(raw); } catch { return void issues.push({ line, reason: 'not JSON' }); }
    if (!isObj(v)) return void issues.push({ line, reason: 'not an object' });
    if (typeof v.kind !== 'string' || !KINDS.has(v.kind)) return void issues.push({ line, reason: `unknown kind ${String(v.kind)}` });
    if (typeof v.t !== 'number' || !Number.isFinite(v.t) || v.t < 0) return void issues.push({ line, reason: 'missing or invalid t' });
    if (v.t < lastT) issues.push({ line, reason: `time goes back (${v.t} after ${lastT}); kept in file order` });
    lastT = Math.max(lastT, v.t);
    recs.push(v as Rec);
  });

  // Target floors, in order: the log's own.
  const meta = recs.find(r => r.kind === 'meta');
  const summary = recs.find(r => r.kind === 'summary');
  let targets: string[] = Array.isArray(meta?.legs) ? (meta!.legs as unknown[]).filter((l): l is string => typeof l === 'string') : [];
  if (!targets.length && str(summary?.floor)) targets = [summary!.floor as string];
  if (!targets.length) {
    const levels = recs.filter(r => r.kind === 'level').map(r => str(r.level)).filter((l): l is string => !!l);
    const deepest = [...levels].sort((a, b) => BASEMENT_ORDER.indexOf(b) - BASEMENT_ORDER.indexOf(a))[0];
    if (deepest) targets = [deepest];
  }
  // run_b2 has no leg records: its casualty is reached at the verdict's own time for that check.
  const verdict = recs.find(r => r.kind === 'verdict');
  let b2Reached: number | null = null;
  if (verdict && isObj(verdict.steps)) {
    for (const [name, s] of Object.entries(verdict.steps)) {
      if (/reached the casualty/i.test(name) && isObj(s) && s.ok === true && typeof s.t === 'number') b2Reached = s.t;
    }
  }

  // Who is on each target floor, when the log names them (run_levels' leg records, reached or not).
  const who = new Map<string, string>();
  for (const r of recs) if (r.kind === 'leg' && str(r.floor) && str(r.casualty)) who.set(r.floor as string, r.casualty as string);

  const stages: RescueStage[] = [{ t: 0, stage: 'start', floor: null, target: targets[0] ?? null, casualty: null,
                                   label: stageLabel({ t: 0, stage: 'start', floor: null, target: targets[0] ?? null, casualty: null }) }];
  let leg = 0;
  let floor: string | null = null;
  let shifted = false;
  const now = () => stages[stages.length - 1];
  const target = () => targets[Math.min(leg, targets.length - 1)] ?? null;
  const go = (t: number, stage: StageId, extra: { casualty?: string | null; ok?: boolean; passed?: number; total?: number } = {}) => {
    const s = { t, stage, floor, target: target(), casualty: extra.casualty ?? who.get(target() ?? '') ?? null };
    const cur = now();
    if (cur.stage === stage && cur.floor === s.floor && cur.target === s.target && stage !== 'reached') return;
    stages.push({ ...s, label: stageLabel(s, extra.passed, extra.total), ...(extra.ok !== undefined ? { ok: extra.ok } : {}) });
  };
  const travel = (t: number) => go(t, floor === target() ? 'search' : 'descend');
  const checks: boolean[] = [];

  for (const r of recs) {
    const t = r.t;
    if (b2Reached !== null && t >= b2Reached && r.kind !== 'verdict' && r.kind !== 'summary') {
      go(b2Reached, 'reached');
      b2Reached = null;
    }
    switch (r.kind) {
      case 'level':
        floor = str(r.level) ?? floor;
        if (!['shift', 'recheck'].includes(now().stage)) travel(t);
        break;
      case 'pose': {
        const lvl = str(r.level);
        if (lvl === 'ramp' && floor !== 'ramp' && now().stage !== 'reached') { floor = 'ramp'; travel(t); }
        else if (lvl && lvl !== 'ramp' && floor === 'ramp') { floor = lvl; travel(t); }
        if (now().stage === 'recheck' && r.state === 'moving') { shifted = false; travel(t); }
        // after a casualty, the next pose (moving, or with no state: run_levels logs none) starts the next leg
        if (now().stage === 'reached' && t > now().t && leg < targets.length && (r.state === undefined || r.state === 'moving')) travel(t);
        break;
      }
      case 'shift':
        floor = str(r.level) ?? floor;
        shifted = true;
        go(t, 'shift');
        break;
      case 'plan':
        if (shifted && now().stage === 'shift') go(t, 'recheck');
        break;
      case 'leg':
        if (r.reached === true) {
          floor = str(r.floor) ?? floor;
          go(t, 'reached');
          leg += 1;
        }
        break;
      case 'step':
        checks.push(r.ok === true);
        break;
      case 'verdict':
        if (isObj(r.steps)) for (const s of Object.values(r.steps)) checks.push(isObj(s) && s.ok === true);
        break;
    }
  }
  if (b2Reached !== null) go(b2Reached, 'reached');
  const end = Math.max(0, ...recs.map(r => r.t));
  if (checks.length || summary) {
    const passed = checks.filter(Boolean).length;
    go(end, 'done', { ok: checks.length > 0 && passed === checks.length, passed, total: checks.length });
  }
  return { stages, targets, issues };
}

/** The stage at sim time t: the last change at or before t. */
export function stageAt(stages: RescueStage[], t: number): RescueStage {
  let cur = stages[0];
  for (const s of stages) { if (s.t <= t) cur = s; else break; }
  return cur;
}

// ---- drawing -------------------------------------------------------------------------------------------

const STYLE_ID = 'rescue-stage-style';
const CSS = `
.rescue-stage { --rs-bg: rgba(10, 16, 29, 0.9); --rs-line: #23334d; --rs-text: #e8f0fa; --rs-dim: #7f93b0;
  display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0.75rem 0.3rem 0.4rem; color: var(--rs-text);
  background: var(--rs-bg); border: 1px solid var(--rs-line); border-radius: 999px; font: 13px/1.3 Inter, system-ui, sans-serif; }
.rescue-stage .rs-dot { flex: none; width: 0.65rem; height: 0.65rem; border-radius: 50%; background: var(--rs-dim); }
.rescue-stage[data-stage="descend"] .rs-dot, .rescue-stage[data-stage="search"] .rs-dot { background: #60a5fa; }
.rescue-stage[data-stage="shift"] .rs-dot { background: #f97316; }
.rescue-stage[data-stage="recheck"] .rs-dot { background: #fbbf24; }
.rescue-stage[data-stage="reached"] .rs-dot, .rescue-stage[data-stage="done"][data-ok="true"] .rs-dot { background: #34d399; }
.rescue-stage[data-stage="done"][data-ok="false"] .rs-dot { background: #f87171; }
.rescue-stage .rs-t { color: var(--rs-dim); font-variant-numeric: tabular-nums; }
`;

/** Draw (or redraw) the stage pill into el, as a polite live region so each change is read out once. */
export function renderRescueStage(el: HTMLElement, s: RescueStage): HTMLElement {
  const doc = el.ownerDocument;
  if (!doc.getElementById(STYLE_ID)) {
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    doc.head.appendChild(style);
  }
  el.setAttribute('aria-live', 'polite');
  const pill = doc.createElement('div');
  pill.className = 'rescue-stage';
  pill.dataset.stage = s.stage;
  if (s.ok !== undefined) pill.dataset.ok = String(s.ok);
  const dot = doc.createElement('span');
  dot.className = 'rs-dot';
  dot.setAttribute('aria-hidden', 'true');
  const label = doc.createElement('span');
  label.textContent = s.label;
  const t = doc.createElement('span');
  t.className = 'rs-t';
  t.textContent = `${Math.round(s.t * 10) / 10} s`;
  pill.append(dot, label, t);
  el.replaceChildren(pill);
  return pill;
}
