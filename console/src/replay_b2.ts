// B2-CONSOLE-REPLAY: replay a B2 rescue run (tools/run_b2.py, runs/b2-<seed>.jsonl) in the console.
//
// run_b2.py logs its own records, one {"t": sim seconds, "kind": ...} per line, not bus envelopes:
//   level {level}                    each level the Scout reaches (L1, ground, B1, B2)
//   pose {pos, state, level, cell}   the Scout's real pose, 1 Hz (no yaw)
//   plan {status, why, target, cells} each (re-)plan; cells are [i, j, k] at 0.05 m
//   shift {xy, level, footprint}     the unscripted change: a slab lands on the route in B2
//   mapped {cells, sources}          the slab cells the Scout mapped from its own measurements
//   summary / verdict                the runner's result and its checked steps
// adaptB2Run() turns them into the bus messages the console already draws, in file order and at the
// recorded sim time, and ReplayPlayer (replay-jsonl.ts) plays them:
//   pose  -> sensors/scout {t, pose: {pos, yaw}}   yaw from the direction of travel (the log has none)
//   plan  -> route/proposed (robot "scout", model "local-astar") when the route's goal or status changes,
//            plus log/decision when the status changes
//   level, mapped -> log/decision
//   shift -> world/change {kind: "aftershock", moved_blocks: ["x1"]} + log/decision (stop and recheck)
//   summary + verdict -> console/replay_b2 {steps, passed, total, reached, ...} (console-only, last event)
// Honesty: ReplayPlayer announces console/replay {source: "replay"} with every step, never live; nothing is
// sent to the hub; data is the runner's own (pos keeps its z, so B1/B2 stay below ground). Unknown or
// malformed lines are reported as issues, never thrown.
//
// Pure module: nothing runs on import. Wiring (not done here, main.ts belongs to the console owner):
//   const { player } = await loadB2Run('/replays/b2-0.jsonl', dispatchBusMessage, { speed: 4 });
//   player.start();

import { ReplayPlayer, type Dispatch, type ParsedRecording, type ParseIssue, type RecordedEvent, type Scheduler }
  from './replay-jsonl';

export const B2_STATUS_TOPIC = 'console/replay_b2';
export const B2_SCENE = 'levels';
export const SLAB_ID = 'x1';                      // run_b2.py drops the levels scene's spare body x1 as the slab
const MODEL = 'local-astar';
const MIN_MOVE_M = 0.01;                          // below this, keep the previous heading

export type B2Step = { name: string; ok: boolean; t: number | null; detail: string };
export type B2Result = {
  steps: B2Step[];
  passed: number;
  total: number;
  reached: boolean | null;
  final_level: string | null;
  final_pos: number[] | null;
  max_jump: number | null;
  levels: string[];
  shift_t: number | null;
};
export type B2Run = ParsedRecording & { result: B2Result; records: number };

type Rec = Record<string, unknown> & { t: number; kind: string };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const isVec = (v: unknown, n: number): v is number[] =>
  Array.isArray(v) && v.length >= n && v.slice(0, n).every(x => typeof x === 'number' && Number.isFinite(x));

const isCells = (v: unknown): v is [number, number, number][] =>
  Array.isArray(v) && v.every(c => isVec(c, 3) && (c as number[]).every(Number.isInteger));

const fmt = (v: number[]) => `[${v.map(x => Math.round(x * 100) / 100).join(', ')}]`;

/** Read run_b2.py's records. Blank lines are ignored; anything else that is not a record is an issue. */
function readRecords(text: string, issues: ParseIssue[]): { rec: Rec; line: number }[] {
  const out: { rec: Rec; line: number }[] = [];
  let lastT = -Infinity;
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = i + 1;
    if (!raw.trim()) return;
    let v: unknown;
    try { v = JSON.parse(raw); } catch { return void issues.push({ line, reason: 'not JSON' }); }
    if (!isRecord(v)) return void issues.push({ line, reason: 'not an object' });
    if (typeof v.kind !== 'string' || !v.kind) return void issues.push({ line, reason: 'missing kind' });
    if (typeof v.t !== 'number' || !Number.isFinite(v.t) || v.t < 0) {
      return void issues.push({ line, reason: 'missing or invalid t' });
    }
    if (v.t < lastT) issues.push({ line, reason: `time goes back (${v.t} after ${lastT}); kept in file order` });
    lastT = Math.max(lastT, v.t);
    out.push({ rec: v as Rec, line });
  });
  return out;
}

/** Turn a run_b2.py log into console bus events (see the header for the mapping). */
export function adaptB2Run(text: string): B2Run {
  const issues: ParseIssue[] = [];
  const records = readRecords(text, issues);
  const events: RecordedEvent[] = [];
  const result: B2Result = { steps: [], passed: 0, total: 0, reached: null, final_level: null, final_pos: null,
                             max_jump: null, levels: [], shift_t: null };
  const push = (t: number, topic: string, data: unknown, line: number) => events.push({ t, topic, data, line });
  const decide = (t: number, line: number, perception: string, outcome: string, reason: string) =>
    push(t, 'log/decision', { t, perception, model: MODEL, physics: '', outcome, reason }, line);

  // Headings from the direction of travel: look ahead to the next pose that moved.
  const poses = records.filter(r => r.rec.kind === 'pose' && isVec(r.rec.pos, 3));
  const yawAt = new Map<number, number>();
  let yaw = 0;
  poses.forEach((p, i) => {
    const here = p.rec.pos as number[];
    for (let j = i + 1; j < poses.length; j++) {
      const there = poses[j].rec.pos as number[];
      if (Math.hypot(there[0] - here[0], there[1] - here[1]) >= MIN_MOVE_M) {
        yaw = Math.atan2(there[1] - here[1], there[0] - here[0]);
        break;
      }
    }
    yawAt.set(p.line, Math.round(yaw * 1000) / 1000);
  });

  let routes = 0;
  let lastKey = '';
  let lastStatus = '';
  let summary: Rec | null = null;
  let verdict: Rec | null = null;
  let endT = 0;
  for (const { rec, line } of records) {
    const t = rec.t;
    endT = Math.max(endT, t);
    switch (rec.kind) {
      case 'pose':
        if (!isVec(rec.pos, 3)) { issues.push({ line, reason: 'pose without pos [x, y, z]' }); break; }
        push(t, 'sensors/scout', { t, pose: { pos: rec.pos.slice(0, 3), yaw: yawAt.get(line) ?? 0 } }, line);
        break;
      case 'plan': {
        const status = typeof rec.status === 'string' ? rec.status : 'unknown';
        const why = typeof rec.why === 'string' ? rec.why : status;
        if (status !== lastStatus) {
          decide(t, line, `Scout plan: ${status}`, status, why);
          lastStatus = status;
        }
        if (!isCells(rec.cells)) { issues.push({ line, reason: 'plan cells are not [i, j, k] integers' }); break; }
        if (rec.cells.length === 0) break;
        const target = isVec(rec.target, 3) ? fmt(rec.target as number[]) : 'unknown';
        const key = `${status}|${target}`;
        if (key === lastKey) break;
        lastKey = key;
        routes += 1;
        push(t, 'route/proposed', { id: `b2-r${routes}`, robot: 'scout', cells: rec.cells, goal: `${status} to ${target}`,
                                     reason: why, model: MODEL }, line);
        break;
      }
      case 'level':
        if (typeof rec.level !== 'string') { issues.push({ line, reason: 'level without a name' }); break; }
        result.levels.push(rec.level);
        decide(t, line, `Scout on ${rec.level}`, 'level', `reached ${rec.level} by driving (no teleport)`);
        break;
      case 'shift': {
        const where = isVec(rec.xy, 2) ? fmt(rec.xy as number[]) : 'unknown';
        const level = typeof rec.level === 'string' ? rec.level : 'unknown';
        result.shift_t = t;
        push(t, 'world/change', { kind: 'aftershock', t, moved_blocks: [SLAB_ID] }, line);
        decide(t, line, `slab landed on the route at ${where} on ${level}`, 'stop_and_recheck',
               'stop short, map the slab from the Scout\'s own measurements, re-plan around it');
        break;
      }
      case 'mapped': {
        const n = typeof rec.cells === 'number' ? rec.cells : 0;
        const src = Array.isArray(rec.sources) ? rec.sources.join(', ') : 'unknown';
        decide(t, line, `${n} slab cell(s) mapped from ${src}`, 'mapped', 'measured by the Scout, not sim truth');
        break;
      }
      case 'summary':
        summary = rec;
        break;
      case 'verdict':
        verdict = rec;
        break;
      default:
        issues.push({ line, reason: `unknown kind ${rec.kind}` });
    }
  }

  if (verdict && isRecord(verdict.steps)) {
    for (const [name, s] of Object.entries(verdict.steps)) {
      if (!isRecord(s)) continue;
      result.steps.push({ name, ok: s.ok === true, t: typeof s.t === 'number' ? s.t : null,
                          detail: typeof s.detail === 'string' ? s.detail : '' });
    }
  }
  result.total = result.steps.length;
  result.passed = result.steps.filter(s => s.ok).length;
  if (summary) {
    result.reached = typeof summary.reached === 'boolean' ? summary.reached : null;
    result.final_level = typeof summary.final_level === 'string' ? summary.final_level : null;
    result.final_pos = isVec(summary.final_pos, 3) ? (summary.final_pos as number[]) : null;
    result.max_jump = typeof summary.max_jump === 'number' ? summary.max_jump : null;
  }
  if (summary || verdict) push(endT, B2_STATUS_TOPIC, { source: 'replay', ...result }, Infinity);
  return { events, issues, meta: null, scene: B2_SCENE, result, records: records.length };
}

/** Adapt a B2 log and make its player (not started). */
export function playB2Run(text: string, dispatch: Dispatch,
                          opts: { source?: string; speed?: number; scheduler?: Scheduler } = {}) {
  const run = adaptB2Run(text);
  const player = new ReplayPlayer(run, dispatch, { ...opts, source: opts.source ?? 'b2 run' });
  return { run, player };
}

/** Fetch a B2 log and make its player (not started). Throws if the file cannot be fetched. */
export async function loadB2Run(url: string, dispatch: Dispatch,
                                opts: { speed?: number; scheduler?: Scheduler } = {}) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`B2 run ${url}: HTTP ${response.status}`);
  return playB2Run(await response.text(), dispatch, { source: url, ...opts });
}
